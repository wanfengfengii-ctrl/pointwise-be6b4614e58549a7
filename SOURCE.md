# 原版仓库与源码

审查对象是 pandas v2.2.2：
https://github.com/pandas-dev/pandas/tree/v2.2.2

这里没有另写一个 merge 实现。bootstrap.py 使用 requirements.txt 的公开固定版本发行包；
probe.run_case 构造显式 dtype 的 DataFrame，直接调用 DataFrame.merge。
准备后发行包内含完整的 pandas Python 源码和测试文件，可在本地阅读。
source_manifest.py 校验 pandas、NumPy 版本及六个相关源码模块的 SHA-256，
给出模块位置和原始符号行号。引用模块相对路径及原始行号，不引用机器专有安装路径。

    python3 bootstrap.py source_manifest.py
    python3 bootstrap.py source_manifest.py --module pandas.core.reshape.merge
    python3 bootstrap.py source_manifest.py --module pandas.core.indexes.base
    python3 bootstrap.py source_manifest.py --module pandas.core.dtypes.cast
    python3 bootstrap.py source_manifest.py --module pandas.core.dtypes.dtypes
    python3 bootstrap.py source_manifest.py --module pandas.core.arrays.numeric
    python3 bootstrap.py source_manifest.py --module pandas.core.frame

源码哈希已分别与题源携带的 macOS、Linux pandas 2.2.2 发行包核对。
NumPy 是 pandas 实际使用的类型与数组依赖；本题不使用 SQLAlchemy 或数据库。
生产源码、source_manifest.py、probe.py、samples.py、checks.py 保持原样。
docs/integer-merge.md 是下游待维护说明，既非上游承诺，也非独立判定器。
