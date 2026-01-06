"""main"""

import asyncio
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import json5
from anyio import Path as AsyncPath
from pydantic import BaseModel
from pydantic_settings import BaseSettings, CliApp

ZIG_VERSION = "zig-x86_64-linux-0.16.0-dev.1912+0cbaaa5eb"
BUSYBOX_VERSION = "busybox-1.37.0"
ARCH_INFO_PATH = Path(__file__).parent.joinpath("arch_info")
BUILD_PATH = Path.cwd().joinpath("build-dir")
BUILD_PATH.mkdir(exist_ok=True)

BUSYBOX_SRC_PATH = BUILD_PATH.joinpath("busybox-src")
ZIG_PATH = BUILD_PATH.joinpath("zig")
BUILD_RESULT_PATH = BUILD_PATH.joinpath("result")
BUILD_RESULT_PATH.mkdir(exist_ok=True)


async def run_cmd(*cmd: str, env: Optional[dict[str, str]] = None, cwd: Optional[Path] = None) -> None:
    """异步运行命令"""
    print(f"run {cmd}")
    proc = await asyncio.create_subprocess_exec(*cmd, env=env, cwd=cwd)
    ret_code = await proc.wait()

    if ret_code != 0:
        msg = f"run {cmd} failed, exit code: {ret_code}"
        raise RuntimeError(msg)


async def run_shell(cmd: str, cwd: Optional[Path]) -> None:
    """异步在 shell 中运行命令"""
    print(f"run {cmd} in shell")
    proc = await asyncio.create_subprocess_shell(cmd, cwd=cwd)
    ret_code = await proc.wait()

    if ret_code != 0:
        msg = f"run {cmd} in shell failed, exit code: {ret_code}"
        raise RuntimeError(msg)


async def init_busybox_src() -> None:
    """初始化 busybox 源码"""
    await run_cmd(
        "wget",
        f"https://busybox.net/downloads/{BUSYBOX_VERSION}.tar.bz2",
        "-O",
        "busybox.tar.bz2",
        cwd=BUILD_PATH,
    )
    await run_cmd("tar", "xvf", "busybox.tar.bz2", cwd=BUILD_PATH)
    shutil.move(BUILD_PATH.joinpath(BUSYBOX_VERSION), BUSYBOX_SRC_PATH)
    await run_shell("cat ../../patch/*.diff|patch -p1", cwd=BUSYBOX_SRC_PATH)


async def init_zig() -> None:
    """初始化 zig"""
    await run_cmd(
        "wget",
        f"https://ziglang.org/builds/{ZIG_VERSION}.tar.xz",
        "-O",
        "zig.tar.gz",
        cwd=BUILD_PATH,
    )
    await run_cmd("tar", "xvf", "zig.tar.gz", cwd=BUILD_PATH)
    shutil.move(BUILD_PATH.joinpath(ZIG_VERSION), ZIG_PATH)


class ArchInfo(BaseModel):
    """编译架构信息"""

    name: str
    clang_target: str
    arch_option: Optional[str] = None
    lld_option: Optional[str] = None


async def build_busybox(path: Path, arch_info: ArchInfo) -> None:
    """编译 busybox"""
    path.mkdir()
    await run_cmd("make", f"O={path}", "defconfig", cwd=BUSYBOX_SRC_PATH)
    config_path = AsyncPath(path).joinpath(".config")
    async with await config_path.open("r", encoding="utf-8") as f:
        config_str = await f.read()
    # 非 x86 架构不支持, 全禁用了省事
    config_str = config_str.replace("\nCONFIG_SHA1_HWACCEL=y\n", "\nCONFIG_SHA1_HWACCEL=n\n")
    # 高版本内核缺失头文件
    config_str = config_str.replace("\nCONFIG_TC=y\n", "\nCONFIG_TC=n\n")
    # 启用内建命令
    config_str += "CONFIG_FEATURE_SH_STANDALONE=y\n"

    async with await config_path.open("w", encoding="utf-8") as f:
        await f.write(config_str)
    await run_cmd("make", f"O={path}", "oldconfig", cwd=BUSYBOX_SRC_PATH)
    print(f"configure {arch_info.name} success")
    if arch_info.arch_option is not None:
        cc = f"zig cc -target {arch_info.clang_target} {arch_info.arch_option}"
    else:
        cc = f"zig cc -target {arch_info.clang_target}"
    lld = f"zig ld.lld {arch_info.lld_option}" if arch_info.lld_option is not None else "zig ld.lld"
    # skip strip 是因为不同架构之间的 strip 不兼容, zig 没打包 strip
    await run_cmd(
        "make",
        f"O={path}",
        f"CC={cc}",
        "CFLAGS=-Os -flto",
        f"LD={lld}",
        "AR=zig ar",
        "SKIP_STRIP=y",
        "-j",
        cwd=BUSYBOX_SRC_PATH,
    )
    shutil.copy(
        path.joinpath("busybox"),
        BUILD_RESULT_PATH.joinpath(f"{arch_info.name}-busybox"),
    )
    print(f"build {arch_info.name} success")


class AsyncSettings(BaseSettings, cli_enforce_required=True):
    """参数"""

    arch_list: Optional[list[str]] = None

    async def cli_cmd(self) -> None:
        """入口"""
        await main(self.arch_list)


async def main(arch_name_list: Optional[list[str]]) -> None:
    """主逻辑"""
    if arch_name_list is None:
        arch_info_async_path = AsyncPath(ARCH_INFO_PATH)
        arch_name_list = [p.stem async for p in arch_info_async_path.iterdir() if p.is_file() and p.suffix == ".json5"]
    print(f"Choose arch list: {arch_name_list}")
    arch_list: list[ArchInfo] = []
    for arch_name in arch_name_list:
        arch_config_path = AsyncPath(ARCH_INFO_PATH).joinpath(f"{arch_name}.json5")
        if not await arch_config_path.exists():
            print(f"Arch config not found: {arch_config_path}")
            sys.exit()
        if not await arch_config_path.is_file():
            print(f"Arch config not file: {arch_config_path}")
            sys.exit()
        async with await arch_config_path.open("r", encoding="utf-8") as f:
            arch_list.append(ArchInfo.model_validate(json5.loads(await f.read())))
    BUILD_PATH.mkdir(exist_ok=True)
    if not BUSYBOX_SRC_PATH.exists():
        await init_busybox_src()

    print("busybox src init success.")

    if not ZIG_PATH.exists():
        await init_zig()
    os.environ["PATH"] = f"{ZIG_PATH}:{os.environ['PATH']}"
    print("zig init success.")

    task_list: list[asyncio.Task[None]] = []
    for arch_info in arch_list:
        build_path = BUILD_PATH.joinpath(arch_info.name)
        if build_path.exists():
            print(f"skip {arch_info.name}")
            continue
        task_list.append(asyncio.create_task(build_busybox(build_path, arch_info=arch_info)))

    await asyncio.gather(*task_list)


if __name__ == "__main__":
    CliApp.run(AsyncSettings)
