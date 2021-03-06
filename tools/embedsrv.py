#!/usr/bin/env python3
#
# Copyright (c) Lexfo
# SPDX-License-Identifier: BSD-3-Clause

import argparse
import binascii
import bz2
import datetime
import hashlib
import os.path
import re
import subprocess
import sys
import types


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
OUTPUT_SCRIPT = os.path.join(PROJECT_DIR, "cli", "rpc2socks", "embexe_data.py")
INPUT_FILES = {
    "EXE32CON": os.path.join(PROJECT_DIR, "svc", "_bin", "rpc2socks32con.exe"),
    "EXE64CON": os.path.join(PROJECT_DIR, "svc", "_bin", "rpc2socks64con.exe"),
    "EXE32SVC": os.path.join(PROJECT_DIR, "svc", "_bin", "rpc2socks32svc.exe"),
    "EXE64SVC": os.path.join(PROJECT_DIR, "svc", "_bin", "rpc2socks64svc.exe")}


def die(*msg, exit_code=1, file=sys.stderr, flush=True, **kwargs):
    print("ERROR:", *msg, file=file, flush=flush, **kwargs)
    sys.exit(exit_code)


def bin2python(infile, *, columns=70, prefix=b"    ", sep=b"\n", compress=True):
    data_raw = infile.read()  # slurp all
    data_size = len(data_raw)
    data_md5 = hashlib.md5(data_raw).hexdigest()

    if compress:
        data_raw = bz2.compress(data_raw, compresslevel=9)
    data_b64 = binascii.b2a_base64(data_raw, newline=False)

    del data_raw

    view = memoryview(data_b64)
    offset = 0
    pylines = b""

    while offset < len(data_b64):
        if pylines:
            pylines += sep
        pylines += prefix + b'b"' + view[offset:offset+columns] + b'"'

        offset += columns

    if not pylines:
        pylines = prefix + b'b""'

    return pylines, data_size, data_md5


def run_and_check_output(*cmd_args, cwd=None, splitlines=True, rstrip=True,
                         **subprocrun_kwargs):
    kwargs = subprocrun_kwargs.copy()
    kwargs["cwd"] = cwd
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("shell", False)
    kwargs.setdefault("check", True)
    kwargs.setdefault("text", True)

    res = subprocess.run(cmd_args, **kwargs)

    if splitlines:
        if isinstance(res.stdout, (bytes, str)):
            res.stdout = [line.rstrip() if rstrip else line
                          for line in res.stdout.splitlines()]
        if isinstance(res.stderr, (bytes, str)):
            res.stderr = [line.rstrip() if rstrip else line
                          for line in res.stderr.splitlines()]
    elif rstrip:
        if isinstance(res.stdout, (bytes, str)):
            res.stdout = res.stdout.rstrip()
        if isinstance(res.stderr, (bytes, str)):
            res.stderr = res.stderr.rstrip()

    return res


def get_git_info(*, repo_dir=None, commit_ish="HEAD", dirty_suffix="-dirty",
                 git_cmd="git"):
    info = types.SimpleNamespace()

    info.describe = run_and_check_output(
        git_cmd, "describe", "--always", "--abbrev", "--dirty=" + dirty_suffix,
        cwd=repo_dir).stdout[0].lstrip()

    if info.describe.endswith(dirty_suffix):
        info.dirty = True
        info.describe = info.describe[0:-len(dirty_suffix)]
    else:
        info.dirty = False

    info.hash = run_and_check_output(
        git_cmd, "rev-parse", commit_ish,
        cwd=repo_dir).stdout[0].lstrip()
    if not re.fullmatch(r"^([a-h\d]{40})$", info.hash, re.A):
        raise RuntimeError("malformed git hash from git rev-parse")

    # info.short = run_and_check_output(
    #     git_cmd, "rev-parse", "--short", commit_ish,
    #     cwd=repo_dir).stdout[0].lstrip()
    # if not re.fullmatch(r"^([a-h\d]{4,40})$", info.short, re.A):
    #     raise RuntimeError("malformed git hash from git rev-parse --short")

    return info


def check_dirs_and_files(context):
    if not PROJECT_DIR:
        die("empty project dir")

    if not os.path.isdir(PROJECT_DIR):
        die("project dir not found:", PROJECT_DIR)

    if context.ignoregit:
        # ignore git all the way even if project dir is a git repo
        context.is_git_repo = False
    elif not os.path.isdir(os.path.join(PROJECT_DIR, ".git")):
        die("project dir not a git repository?", PROJECT_DIR)
    else:
        context.is_git_repo = True

    for file in INPUT_FILES.values():
        if not os.path.isfile(file):
            die("input file not found:", file)

    if not os.path.isdir(os.path.dirname(OUTPUT_SCRIPT)):
        die("parent dir of output file not found:",
            os.path.dirname(OUTPUT_SCRIPT))

    return context


def generate_python_script(context):
    now_str = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")

    if not context.is_git_repo:
        git_commit = "None"
        # git_dirty = "None"
    else:
        git_commit = f'"{context.git_info.hash}"  # CAUTION: repo possibly dirty'
        # git_dirty = "True" if context.git_info.dirty else "False"

    with open(context.outfile, mode="wb") as fout:
        header = (
            f"# Copyright (c) Lexfo\n"
            f"# SPDX-License-Identifier: BSD-3-Clause\n"
            f"#\n"
            f"# auto-generated by {os.path.basename(__file__)}\n"
            f"#\n"
            f"\n"
            f"GENERATED_AT = \"{now_str}\"\n"
            f"GIT_COMMIT = {git_commit}\n")
            # f"GIT_DIRTY = {git_dirty}\n")

        fout.write(header.encode())

        for name, infile in INPUT_FILES.items():
            with open(infile, mode="rb") as fin:
                textified, data_size, data_md5 = bin2python(fin)

            header = (
                "\n"
                "\n"
                f"# {os.path.basename(infile)}\n"
                f"{name}_SIZE = {data_size}  # uncompressed size\n"
                f"{name}_MD5 = \"{data_md5}\"  # on uncompressed data\n"
                f"{name}_DATA = (  # compressed with bz2 and encoded in base64\n")

            fout.write(header.encode())
            fout.write(textified)
            fout.write(b")\n")


def parse_args(args):
    parser = argparse.ArgumentParser(
        allow_abbrev=False, add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Embed SVC executables into " + OUTPUT_SCRIPT)

    # parser.add_argument(
    #     "--ignoregit", action="store_true",
    #     help="Bypass the git repo check")

    # parser.add_argument(
    #     "--ignoredirty", action="store_true",
    #     help="Bypass the dirty git repo check")

    parser.add_argument(
        "--help", "-h", action="help", default=argparse.SUPPRESS,
        help="Show this help message and leave")

    opts = parser.parse_args(args)

    context = types.SimpleNamespace()
    context.ignoregit = True  # opts.ignoregit
    # context.ignoredirty = opts.ignoredirty
    context.repodir = PROJECT_DIR
    context.outfile = OUTPUT_SCRIPT

    return context


def main(args=None):
    args = sys.argv[1:] if args is None else args[:]
    context = parse_args(args)

    context = check_dirs_and_files(context)
    if context.is_git_repo:
        context.git_info = get_git_info(repo_dir=context.repodir)

    generate_python_script(context)
    print("generated", context.outfile)

    return 0


if __name__ == "__main__":
    sys.exit(main())
