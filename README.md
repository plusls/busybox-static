# busybox static

使用 zig 自动构建静态 busybox

版本: 1.37

支持架构:

+ mipsel-linux-musleabi
+ mips-linux-musleabi
+ mips64-linux-muslabi64
+ mips64el-linux-muslabi64
+ arm-linux-musleabi
+ aarch64-linux-musl
+ powerpc-linux-musleabi
+ powerpc64-linux-musl
+ powerpc64le-linux-musl
+ thumb-linux-musleabi
+ x86_64-linux-musl
+ x86-linux-musl

## 使用

样例

```
uv run python3 main.py --arch_list mips64-linux-muslabi64 --arch_list x86-linux-musl-busybox
```

不加参数会编译所有架构


```
uv run python3 main.py
```

架构信息见 `arch_info` 目录

## config

启用/禁用了如下配置

### enable

+ CONFIG_FEATURE_SH_STANDALONE: 对于 busybox 的内建命令会直接执行 busybox，而不是寻找 path

### disable

+ CONFIG_TC: 高版本内核缺失头文件会导致编译失败
+ CONFIG_SHA1_HWACCEL: 非 x86 架构无硬件实现, 会编译失败

## patch

会自动应用如下补丁

### fix-x86-pstm

clang 编译 x86 的 busybox 时 pstm 中的内联汇编会寄存器分配失败, 回退到 c 实现

### fix-lld-link

llvm 的 lld 不支持特定的 gcc ld link 参数, 进行 patch

### fix-libncurse-clang-warning

clang 编译时会产生 warning 导致失败

### fix-clang-optimization

BB_GLOBAL_CONST 用了一些 ub, gcc 行为和 clang 不一致, 会导致该区域被优化到 rodata 导致段错误, 就行修复
