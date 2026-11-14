# pandas 整数标识关联维护工作区

数据加工链路使用固定版本 pandas 合并有符号和无符号整数标识。
小整数正常回归通过，但公开大整数样例违反现有使用说明。
本轮产物是代码审查、修订说明和可重跑证据；不要求开发新关联器。

使用 Python 3.9–3.12。先运行：
    python3 bootstrap.py --prepare
    python3 bootstrap.py checks.py normal

已有固定 pandas/NumPy 时直接使用；否则在 .review-venv 安装 requirements.txt。
首次准备从公开包索引取得依赖；准备后查看源码和重跑不需要网络，
没有数据库服务、账号或外部业务数据。
源码出处及完整读取入口见 SOURCE.md，观察格式和维护约定见 CONTRACT.md。
运行 python3 bootstrap.py probe.py incident 可查看原 API 的真实输出。
