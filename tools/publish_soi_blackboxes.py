# -*- coding: utf-8 -*-
# 时间: 2026-11

"""先发布已提交的私有白盒，再仅同步有变化的公开黑盒。"""

import argparse
import base64
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tempfile


ORG = "Jinan-Photonics-Integration-Center"
PDK = f"{ORG}/JNU-MWP-SOI-PDK"
LIBRARY = f"{ORG}/JNU-MWP-SOI-Library"
PDK_URL = f"https://github.com/{PDK}.git"
LIBRARY_URL = f"https://github.com/{LIBRARY}.git"
DEV_REF = re.compile(r"refs/heads/JNU_MWP_PDK_V[0-9]+\.[0-9]+")
ROOT = Path(__file__).resolve().parents[1]
PYMACROS = Path("salt/JNU_MWP_PDK/pymacros")
BLACKBOX_DIR = PYMACROS / "JNU_MWP_blackbox_gds"
CONVERTER = ROOT / PYMACROS / "JNU_MWP_tools/release/sync_blackboxes_from_library.py"
MUTATION = """
mutation ($input: CreateCommitOnBranchInput!) {
  createCommitOnBranch(input: $input) { commit { url } }
}
"""


def git(*args, cwd=None):
    return subprocess.check_output(["git", *map(str, args)], cwd=cwd)


def development_ref(url):
    refs = git("ls-remote", "--heads", url, "refs/heads/JNU_MWP_PDK_V*").decode("utf-8")
    matches = [ref for line in refs.splitlines() if DEV_REF.fullmatch(ref := line.split("\t")[-1])]
    if len(matches) != 1:
        raise RuntimeError("需要恰好一个现有 SOI PDK 版本开发分支。")
    return matches[0]


def push_library(directory):
    allowed = {url.casefold().removesuffix(".git") for url in (
        LIBRARY_URL, f"git@github.com:{LIBRARY}", f"ssh://git@github.com/{LIBRARY}",
    )}
    origins = git("remote", "get-url", "--push", "--all", "origin", cwd=directory).decode().splitlines()
    if len(origins) != 1 or origins[0].casefold().removesuffix(".git") not in allowed:
        raise RuntimeError("拒绝推送：该克隆的 origin 不是指定私有白盒仓库。")
    if git("branch", "--show-current", cwd=directory).strip() != b"main":
        raise RuntimeError("请从白盒仓库的 main 分支发布。")
    if git("status", "--porcelain", cwd=directory):
        raise RuntimeError("白盒仓库有未提交的文件，请先核对并提交。")
    subprocess.run(["git", "push", "origin", "HEAD:refs/heads/main"], cwd=directory, check=True)


def blackbox_changes(target):
    records = git("diff", "--cached", "--name-status", "--no-renames", "-z", cwd=target)
    fields = records.decode("utf-8").split("\0")[:-1]
    additions, deletions = [], []
    for status, name in zip(fields[::2], fields[1::2], strict=True):
        path = PurePosixPath(name)
        if (path.parent != PurePosixPath(BLACKBOX_DIR.as_posix())
                or path.suffix != ".gds" or path.name.startswith("Pcell_")):
            raise RuntimeError("提交包含固定黑盒 GDS 目录以外的文件。")
        if status == "D":
            deletions.append({"path": name})
        elif status in {"A", "M"}:
            mode = git("ls-files", "--stage", "--", name, cwd=target).split()[0]
            blob = git("show", ":" + name, cwd=target)
            if mode != b"100644" or blob != (target / name).read_bytes():
                raise RuntimeError("暂存的黑盒必须与已验证的普通 GDS 文件一致。")
            additions.append({"path": name, "contents": base64.b64encode(blob).decode("ascii")})
        else:
            raise RuntimeError("意外的黑盒文件变更类型。")
    return {"additions": additions, "deletions": deletions}


def prepare(library_url=LIBRARY_URL, pdk_url=PDK_URL):
    ref = development_ref(pdk_url)
    with tempfile.TemporaryDirectory(prefix="jnu-soi-blackbox-publish-") as folder:
        library = Path(folder).resolve() / "library"
        target = Path(folder).resolve() / "target"
        git("clone", "--quiet", "--single-branch", "--depth=1", "--branch", "main",
            library_url, library)
        git("clone", "--quiet", "--single-branch", "--depth=1", "--branch",
            ref.removeprefix("refs/heads/"), pdk_url, target)
        base = git("rev-parse", "HEAD", cwd=target).decode("ascii").strip()
        output = target / BLACKBOX_DIR
        if output.resolve() != output or any(path.is_symlink() for path in output.iterdir()):
            raise RuntimeError("黑盒目录或文件不得使用符号链接。")
        subprocess.run(
            [sys.executable, str(CONVERTER), "--source", str(library / "JNU_MWP_gds"),
             "--output", str(output)], check=True,
        )
        git("add", "-A", "--", f":(glob){BLACKBOX_DIR.as_posix()}/*.gds", cwd=target)
        changes = blackbox_changes(target)

    if not any(changes.values()):
        return None
    return {
        "query": MUTATION,
        "variables": {"input": {
            "branch": {"repositoryNameWithOwner": PDK, "refName": ref},
            # 仅追加到核对过的分支末端；远端分支推进或改名时拒绝覆盖。
            "expectedHeadOid": base,
            "message": {"headline": "Synchronize fixed SOI blackbox devices"},
            "fileChanges": changes,
        }},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push-library", type=Path, metavar="LIBRARY_CHECKOUT",
                        help="先推送指定白盒克隆的已提交 main")
    parser.add_argument("--publish", action="store_true", help="有黑盒变化时发布；省略仅检查")
    args = parser.parse_args()
    if args.push_library and not args.publish:
        parser.error("--push-library 必须与 --publish 一起使用")
    if args.push_library:
        push_library(args.push_library.resolve())

    payload = prepare()
    if payload is None:
        print("黑盒与远端开发分支一致，不产生提交。")
        return
    changes = payload["variables"]["input"]["fileChanges"]
    print("待同步黑盒：新增或更新 %d 个，移除 %d 个。" %
          (len(changes["additions"]), len(changes["deletions"])), flush=True)
    if args.publish:
        subprocess.run(
            ["gh", "api", "graphql", "--input", "-", "--jq", ".data.createCommitOnBranch.commit.url"],
            input=json.dumps(payload), encoding="utf-8", check=True,
        )


if __name__ == "__main__":
    main()
