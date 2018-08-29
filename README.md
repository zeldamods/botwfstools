# botwfstools

Tools for exploring and editing Breath of the Wild's ROM

## Requirements
* Python 3.6+
* [fusepy](https://github.com/fusepy/fusepy): download and install 3.0.0 **from GitHub**
* [WinFsp](http://www.secfs.net/winfsp/download/) if you're on Windows

## Quick usage

Make sure you've got all of the requirements listed above, then run `pip install botwfstools`.

Then run:

    botw-edit --content-view ...  --patch-dir ... --work-dir ...
              --target {wiiu,switch}
              PATH_TO_GAME_DUMP

**PATH_TO_GAME_DUMP** is a path to Breath of the Wild content files,
such that PATH_TO_GAME_DUMP/System/Version.txt exists.

The **content view** is where the content files will be mounted,
with all archives shown as directories.

Any files you edit will be saved into the **work directory** to avoid clobbering your game dump.

When you type patch, the tool automatically repacks all of the modified files and fixes the RSTB.
Modified files, repacked archives and the updated RSTB are put into the **patch directory**.
This directory contains files that can be used on console with LayeredFS for example.

The **patched view** is the result of applying the patches to the game dump.
It's what the game would actually see on console with LayeredFS. This is useful for emulators.
If this is something you want to use, add `--patched-view <path to patched view here>`
to the command line. You can omit the patch dir if seeing the patched archives is not useful to you.

Make sure that the work directory exists. However on Windows please ensure the content view
and patched view directories do *not* exist.

## botw-overlayfs

Allows overlaying several game content directories and presenting a single merged view.

    botw-overlayfs  CONTENT_DIRS   TARGET_MOUNT_DIR

Pass as many content directories (layers) as required.
Directories take precedence over the ones on their left.

By default, the view is read-only. If you pass `--workdir` then any files you modify or create
in the view will be transparently saved to the work directory. Useful for modifying game files
without trashing the original files and without having to keep large backups.

Usage example:

    botw-overlayfs  botw/base/ botw/update/   botw/merged/

Then you can access `botw/merged/System/Version.txt` and have it show 1.5.0.

## botw-contentfs

A tool to make game content extremely easy to access and modify.

Files that are in archives can be read and written to
*without having to unpack/repack an archive ever*.

    botw-contentfs  CONTENT_DIR   TARGET_MOUNT_DIR

By default, the view is read-only. If you pass `--workdir` then any files you modify or create
in the view will be transparently saved to the work directory. Extremely useful when used
in conjunction with the patcher (see below) for effortlessly patching game files.

Usage example:

    botw-contentfs  botw/merged/   botw/content/ --workdir botw/mod-files/

You can now access files that are in SARCs directly! Example: `botw/content/Pack/Bootup.pack/Actor/GeneralParamList/Dummy.bgparamlist`

## botw-patcher

Converts an extracted content patch directory into a loadable content layer.

This tool will repack any extracted archives and update the file sizes
in the Resource Size Table automatically.

    patcher  ORIGINAL_CONTENT_DIR   MOD_DIR  TARGET_DIR  --target {wiiu,switch}

Usage example:

    patcher  botw/merged/  botw/mod-files/  botw/patched-files/

The patched files can be used on console or with botw-overlayfs.

## botw-edit

A convenience wrapper that combines contentfs, overlayfs and patcher.

    botw-edit --content-view CONTENT_VIEW
              --patched-view PATCHED_VIEW
              --patch-dir PATCH_DIR
              --work-dir WORK_DIR
              --target {wiiu,switch}
              CONTENT_DIRECTORIES

CONTENT_VIEW is the path to the directory where the extracted view should be mounted.

WORK_DIR is where files you modify and create will be stored.

PATCH_DIR is where repacked files should be stored. Useful if you intend to distribute
your modified content files or use them on console with LayeredFS for example.
(Optional if PATCHED_VIEW is passed.)

PATCHED_VIEW is where the patched view should be mounted. If you use cemu for example,
this can be the path to the title content directory: `/mlc01/usr/title/00050000/101C9500/content/`
(Optional if PATCH_DIR is passed.)

For CONTENT_DIRECTORIES, pass the base content directory, then the update content.

Usage example:

    botw-edit --content-view botw/view/  --patched-view wiiu/mlc01/usr/title/00050000/101C9500/content/
              --work-dir botw/patches/
              --target wiiu
              botw/base/ botw/update/

Then you can edit files in `botw/view/` and test them immediately, without ever having to keep
unneeded copies or manually create archives.

## License

This software is licensed under the terms of the GNU General Public License, version 2 or later.
