#!/usr/bin/env python3
# Copyright 2018 leoetlino <leo@leolam.fr>
# Licensed under MIT

import abc
import argparse
import errno
import functools
import io
import os
from pathlib import PurePosixPath as PPPath
import sarc
import shutil
import stat
import sys
import threading
import typing

from fuse import FUSE, FuseOSError, Operations # type: ignore

BINARY_MODE = os.O_BINARY if os.name == 'nt' else 0

ARCHIVE_EXTS = {'sarc', 'pack', 'bactorpack', 'bmodelsh', 'beventpack', 'stera', 'stats',
                'ssarc', 'spack', 'sbactorpack', 'sbmodelsh', 'sbeventpack', 'sstera', 'sstats',
                'blarc', 'sblarc', 'genvb', 'sgenvb', 'bfarc', 'sbfarc'}

def is_archive_filename(path: PPPath) -> bool:
    return path.suffix[1:] in ARCHIVE_EXTS

class File(metaclass=abc.ABCMeta):
    __slots__ = ()
    @abc.abstractclassmethod
    def read(self, length: int) -> bytes:
        pass
    @abc.abstractclassmethod
    def write(self, buffer) -> int:
        pass
    @abc.abstractclassmethod
    def seek(self, offset: int) -> int:
        pass
    @abc.abstractclassmethod
    def get_size(self) -> int:
        pass

class HostFile(File):
    __slots__ = ('_fh')
    def __init__(self, fh) -> None:
        self._fh = fh
    def __del__(self) -> None:
        os.close(self._fh)
    def read(self, count: int) -> bytes:
        return os.read(self._fh, count)
    def write(self, data) -> int:
        return os.write(self._fh, data)
    def seek(self, offset: int) -> int:
        return os.lseek(self._fh, offset, os.SEEK_SET)
    def get_size(self) -> int:
        return os.fstat(self._fh).st_size

class InMemoryFile(File):
    __slots__ = ('_data', '_position')
    def __init__(self, data: memoryview) -> None:
        self._data = data
        self._position = 0
    def read(self, count: int) -> bytes:
        actual_count = count
        if self._position + count > len(self._data):
            actual_count = len(self._data) - self._position
        if actual_count <= 0:
            return bytes()
        return self._data[self._position:self._position + actual_count].tobytes()
    def write(self, data) -> int:
        raise FuseOSError(errno.EROFS)
    def seek(self, offset: int) -> int:
        self._position = offset
        return offset
    def get_size(self) -> int:
        return len(self._data)

class Directory(metaclass=abc.ABCMeta):
    __slots__ = ('_path', '_base_path')
    def __init__(self, base_path: PPPath, path: PPPath) -> None:
        self._path = path
        self._base_path = base_path
    def get_path_relative_to_this(self, partial: PPPath) -> PPPath:
        return partial.relative_to(self._path.relative_to(self._base_path))
    @abc.abstractclassmethod
    def list_files(self, path: PPPath) -> typing.Collection[str]:
        pass
    @abc.abstractclassmethod
    def open_file(self, file: PPPath, flags) -> File:
        pass
    @abc.abstractclassmethod
    def get_file_stats(self, path: PPPath) -> dict:
        pass

# To work around a stupid readonly attribute limitation.
def my_stat(st) -> dict:
    d = dict((key, getattr(st, key)) for key in ('st_atime', 'st_ctime',
             'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))
    if os.name != 'nt':
        d['st_blocks'] = st.st_blocks
    return d

def change_st_to_directory(st) -> None:
    st['st_mode'] &= ~stat.S_IFREG
    st['st_mode'] |= stat.S_IFDIR
    st['st_mode'] |= stat.S_IRWXU
    st['st_size'] = 0

class HostDirectory(Directory):
    __slots__ = ()
    def __init__(self, base_path: PPPath, path: PPPath) -> None:
        super().__init__(base_path, path)

    def list_files(self, path: PPPath) -> typing.Collection[str]:
        return os.listdir(self._path / path)

    def open_file(self, file: PPPath, flags) -> File:
        return HostFile(os.open(self._path / file, flags | BINARY_MODE))

    def get_file_stats(self, path: PPPath) -> dict:
        return my_stat(os.lstat(self._path / path))

class ArchiveDirectory(Directory):
    __slots__ = ('_arc', '_parent')
    SELF_FILE_NAME = '.__RAW_ARCHIVE__'

    def __init__(self, base_path: PPPath, path: PPPath, archive: sarc.SARC, parent: Directory) -> None:
        super().__init__(base_path, path)
        self._arc = archive
        self._parent = parent

    def list_files(self, path: PPPath) -> typing.Collection[str]:
        names: typing.Set[str] = set()
        directory = str(path) + '/' if str(path) != '.' else ''
        for name in self._arc.list_files():
            if directory and not name.startswith(directory):
                continue
            # Strip leading slashes. These cannot be used in file names.
            if name[0] == '/':
                name = name[1:]
            name = name[len(directory):]
            slash_position = name.find('/')
            if slash_position != -1:
                names.add(name[:slash_position])
            else:
                names.add(name)
        if directory == '':
            names.add(ArchiveDirectory.SELF_FILE_NAME)
        return names

    def open_file(self, file: PPPath, flags) -> File:
        if str(file) == ArchiveDirectory.SELF_FILE_NAME:
            return self._parent.open_file(self._path.relative_to(self._parent._path), os.O_RDONLY)
        try:
            return InMemoryFile(self._arc.get_file_data(str(file)))
        except KeyError:
            # Some archives have leading slashes.
            return InMemoryFile(self._arc.get_file_data('/' + str(file)))
    def get_file_stats(self, path: PPPath) -> dict:
        # Use the SARC's stats to get correct-ish timestamps and other metadata easily.
        arc_stat = self._parent.get_file_stats(self._path.relative_to(self._parent._path))
        if str(path) == ArchiveDirectory.SELF_FILE_NAME:
            return arc_stat

        for arc_file in self._arc.list_files():
            if arc_file == str(path) or arc_file == '/' + str(path):
                arc_stat['st_mode'] &= ~stat.S_IFDIR
                arc_stat['st_mode'] &= ~stat.S_IXUSR
                arc_stat['st_mode'] |= stat.S_IFREG
                arc_stat['st_mode'] |= stat.S_IRUSR | stat.S_IWUSR
                arc_stat['st_size'] = self._arc.get_file_size(arc_file)
                return arc_stat

            if str(path) + '/' in arc_file:
                change_st_to_directory(arc_stat)
                return arc_stat

        raise FuseOSError(errno.ENOENT)

T = typing.TypeVar('T')
class FdAllocator(typing.Generic[T]):
    def __init__(self) -> None:
        self._fd_map: typing.Dict[int, T] = dict()
        self._next_fd = 0

    def allocate(self, item: T) -> int:
        fd = self._next_fd
        while True:
            if fd not in self._fd_map:
                self._fd_map[fd] = item
                self._next_fd = fd + 1
                return fd
            fd += 1

    def free(self, fd) -> None:
        del self._fd_map[fd]
        self._next_fd = min(self._next_fd, fd)

    def get_entry(self, fd) -> T:
        return self._fd_map[fd]

class ContentDirectory(Directory):
    __slots__ = ('_content_device', '_rel_path')
    def __init__(self, base_path: PPPath, path: PPPath, content_device) -> None:
        super().__init__(base_path, path)
        self._content_device = content_device
        self._rel_path = path.relative_to(base_path)

    def _do_list_files(self, path: PPPath) -> typing.Collection[str]:
        entries = set()
        for d in reversed(self._content_device.dirs):
            try:
                entries.update(os.listdir(d / self._rel_path / path))
            except FileNotFoundError:
                pass
        return entries

    @functools.lru_cache(maxsize=2**15)
    def _find_parent(self, path: PPPath, existence_fn: typing.Callable[[PPPath], bool]) -> PPPath:
        if str(path) == '.':
            return self._content_device.dirs[-1]
        for d in reversed(self._content_device.dirs):
            try:
                if existence_fn(d / path):
                    return d
            except FileNotFoundError:
                pass
        raise FuseOSError(errno.ENOENT)

    def list_files(self, path):
        return self._do_list_files(path)

    def open_file(self, file: PPPath, flags) -> File:
        p = self._rel_path / file
        return HostFile(os.open(self._find_parent(p, os.path.isfile) / p, flags | BINARY_MODE))

    @functools.lru_cache(maxsize=2**13)
    def _do_get_file_stats(self, path: PPPath) -> dict:
        p = self._rel_path / path
        return dict(my_stat(os.lstat(self._find_parent(p, os.path.exists) / p)))

    def get_file_stats(self, path):
        return self._do_get_file_stats(path)

class ContentDevice:
    ROOT_STR = '!!!content!!!'
    ROOT = PPPath(ROOT_STR)

    def __init__(self, content_dirs: typing.List[PPPath]) -> None:
        self.dirs = content_dirs

    @functools.lru_cache(maxsize=2**15)
    def isdir(self, path: PPPath) -> bool:
        return any(os.path.isdir(str(path).replace(self.ROOT_STR, str(d))) for d in reversed(self.dirs))

    @functools.lru_cache(maxsize=2**15)
    def try_open_dir(self, path: PPPath) -> typing.Optional[ContentDirectory]:
        for d in reversed(self.dirs):
            if os.path.isdir(str(path).replace(self.ROOT_STR, str(d))):
                return ContentDirectory(self.ROOT, path, self)
        return None

    def is_content_path(self, path: PPPath) -> bool:
        return path.parts[0] == self.ROOT_STR

class BotWContent(Operations):
    def __init__(self, content_device: ContentDevice, work_dir: typing.Optional[str]) -> None:
        self.content_device = content_device
        self.work_dir = PPPath(work_dir) if work_dir else None
        self.sarcs: typing.Dict[str, sarc.SARC] = dict()
        self.fd_map: FdAllocator[File] = FdAllocator()
        self.fd_lock = threading.Lock()

    @functools.lru_cache(maxsize=64)
    def _get_sarc(self, base_path: PPPath, path: PPPath) -> typing.Tuple[Directory, sarc.SARC]:
        parent = self._get_directory(base_path, path.parent)
        archive_file = parent.open_file(parent.get_path_relative_to_this(path), os.O_RDONLY)
        archive = sarc.read_file_and_make_sarc(
            io.BytesIO(archive_file.read(archive_file.get_size())))
        if archive:
            return (parent, archive)
        raise FuseOSError(errno.ENOENT)

    def _get_directory(self, base_path: PPPath, path: PPPath) -> Directory:
        while True:
            full_path = base_path / path
            if self.content_device.is_content_path(full_path):
                content_dir = self.content_device.try_open_dir(full_path)
                if content_dir:
                    return content_dir
                if is_archive_filename(full_path) and not self.content_device.isdir(full_path):
                    directory, archive = self._get_sarc(base_path, path)
                    return ArchiveDirectory(base_path, full_path, archive, directory)
            else:
                if os.path.isdir(full_path):
                    return HostDirectory(base_path, full_path)
                if is_archive_filename(full_path) and not os.path.isdir(full_path):
                    directory, archive = self._get_sarc(base_path, path)
                    return ArchiveDirectory(base_path, full_path, archive, directory)
            path = path.parent

    def _get_file(self, base_path: PPPath, path: PPPath, flags) -> File:
        parent = self._get_directory(base_path, path.parent)
        return parent.open_file(parent.get_path_relative_to_this(path), flags)

    @functools.lru_cache(maxsize=256)
    def _get_directory_from_content(self, path: PPPath) -> Directory:
        return self._get_directory(ContentDevice.ROOT, path)

    @functools.lru_cache(maxsize=256)
    def _get_file_from_content(self, path: PPPath, flags) -> File:
        return self._get_file(ContentDevice.ROOT, path, flags)

    def _get_parent_directory_from_partial(self, path: PPPath) -> Directory:
        if self.work_dir and os.path.exists(self.work_dir / path):
            return self._get_directory(self.work_dir, path.parent)
        return self._get_directory_from_content(path.parent)

    def _get_file_from_partial(self, path: PPPath, flags) -> File:
        if self.work_dir and os.path.isfile(self.work_dir / path):
            return self._get_file(self.work_dir, path, flags)
        return self._get_file_from_content(path, flags)

    def _path(self, partial: str) -> PPPath:
        return PPPath(partial[1:] if partial[0] == '/' else partial)

    def access(self, partial: str, mode):
        pass

    def getattr(self, partial: str, fh=None):
        _path = self._path(partial)

        parent = self._get_parent_directory_from_partial(_path)
        st = parent.get_file_stats(parent.get_path_relative_to_this(_path))
        if is_archive_filename(_path):
            change_st_to_directory(st)
        return st

    def readdir(self, partial: str, fh) -> typing.Iterator[str]:
        entries = set(['.', '..'])

        if self.work_dir:
            real_path = self.work_dir / self._path(partial)
            if os.path.isdir(real_path):
                entries.update(os.listdir(real_path))

        try:
            _path = self._path(partial)
            directory = self._get_directory_from_content(_path)
            entries.update(directory.list_files(directory.get_path_relative_to_this(_path)))
        except FuseOSError:
            pass

        for r in entries:
            yield r

    def rmdir(self, partial: str):
        _path = self._path(partial)
        if not self.work_dir or not os.path.exists(self.work_dir / _path):
            raise FuseOSError(errno.EROFS)
        return os.rmdir(self.work_dir / _path)

    def mkdir(self, partial: str, mode):
        _path = self._path(partial)
        if not self.work_dir:
            raise FuseOSError(errno.EROFS)
        # TODO: error if the parent does not exist?
        return os.makedirs(self.work_dir / _path, mode)

    def statfs(self, partial: str):
        if os.name == 'nt':
            usage = shutil.disk_usage(str(self.content_device.dirs[0]))
            return {
                # Just return everything in bytes.
                'f_frsize': 1,
                'f_blocks': usage.total,
                'f_bfree': usage.free,
            }

        stv = os.statvfs(self.content_device.dirs[0])
        return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
            'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
            'f_frsize', 'f_namemax'))

    def unlink(self, partial: str):
        _path = self._path(partial)
        if not self.work_dir or not os.path.exists(self.work_dir / _path):
            raise FuseOSError(errno.EROFS)
        return os.unlink(self.work_dir / _path)

    def rename(self, old: str, new: str):
        if not self.work_dir or not os.path.exists(self.work_dir / self._path(old)):
            raise FuseOSError(errno.EROFS)
        return os.rename(self.work_dir / self._path(old), self.work_dir / self._path(new))

    def utimens(self, path, times=None):
        pass

    def open(self, partial: str, flags) -> int:
        with self.fd_lock:
            _path = self._path(partial)
            if (flags & os.O_WRONLY or flags & os.O_RDWR):
                if not self.work_dir:
                    raise FuseOSError(errno.EROFS)
                if not os.path.exists(self.work_dir / _path):
                    os.makedirs(self.work_dir / _path.parent, exist_ok=True)
                    with open(self.work_dir / _path, 'wb') as target:
                        file = self._get_file_from_content(_path, os.O_RDONLY)
                        target.write(file.read(file.get_size())) # type: ignore
                return self.fd_map.allocate(HostFile(os.open(self.work_dir / _path, flags | BINARY_MODE)))
            return self.fd_map.allocate(self._get_file_from_partial(_path, os.O_RDONLY))

    def create(self, partial: str, mode, fi=None):
        if not self.work_dir:
            raise FuseOSError(errno.EROFS)
        with self.fd_lock:
            # TODO: error if the parent dir does not exist
            os.makedirs(self.work_dir / self._path(partial).parent, exist_ok=True)
            return self.fd_map.allocate(
                HostFile(os.open(self.work_dir / self._path(partial), os.O_RDWR | os.O_CREAT | BINARY_MODE, mode)))

    def read(self, partial: str, length, offset, fd: int):
        with self.fd_lock:
            file = self.fd_map.get_entry(fd)
            file.seek(offset)
            return file.read(length)

    def write(self, partial: str, buf, offset, fd: int):
        with self.fd_lock:
            file = self.fd_map.get_entry(fd)
            file.seek(offset)
            return file.write(buf)

    def truncate(self, partial: str, length, fh=None):
        _path = self._path(partial)
        if not self.work_dir:
            raise FuseOSError(errno.EROFS)
        with open(self.work_dir / _path, 'r+b') as f:
            f.truncate(length)

    def flush(self, path, fd: int):
        pass

    def release(self, path, fd: int):
        with self.fd_lock:
            self.fd_map.free(fd)

    def fsync(self, path, fdatasync, fd: int):
        return self.flush(path, fd)

def _exit_if_not_dir(path: str):
    if not os.path.isdir(path):
        sys.stderr.write('error: %s is not a directory\n' % path)
        sys.exit(1)

def main(content_dirs: typing.List[str], target_dir: str, work_dir: typing.Optional[str]) -> None:
    for d in content_dirs:
        _exit_if_not_dir(d)
    if work_dir:
        _exit_if_not_dir(work_dir)

    content_dirs = [os.path.realpath(d) for d in content_dirs]
    target_dir = os.path.realpath(target_dir)

    for d in content_dirs:
        print('content: %s' % d)
    print('target: %s' % target_dir)
    if work_dir:
        print('work: %s' % work_dir)
    else:
        print('work: (none, read-only)')

    content_device = ContentDevice([PPPath(d) for d in content_dirs])

    if os.name != 'nt':
        FUSE(BotWContent(content_device, work_dir), target_dir, foreground=True)
    else:
        FUSE(BotWContent(content_device, work_dir), target_dir, foreground=True,
             uid=65792, gid=65792, umask=0)

def cli_main() -> None:
    parser = argparse.ArgumentParser(description='Presents an extracted content view.')
    parser.add_argument('content_dirs', nargs='+', help='Path to the content directory.')
    parser.add_argument('target_mount_dir', help='Path to the directory on which the merged view should be mounted')
    parser.add_argument('-w', '--workdir', help='Path to the directory where modified/new files will be stored (in an extracted form). Assumed not to contain archives.')

    args = parser.parse_args()
    main(content_dirs=args.content_dirs, target_dir=args.target_mount_dir, work_dir=args.workdir)

if __name__ == '__main__':
    cli_main()
