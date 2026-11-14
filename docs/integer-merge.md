# 数据加工中的整数标识关联

适用：pandas 2.2.2，`how` 为 `inner` 或 `left`，`sort=False`；两侧标识分别声明
`int64`、`uint64` 或对应可空 `Int64`、`UInt64`。标识按精确整数身份比较，不作
金额或近似数处理。本文区分三件事：**2.2.2 当前实际行为**、**本版本可用的调用方
规避**、**建议上游采用的最小修复**。后两者都不是现版本已提供的保证。

## 一、2.2.2 的当前实际行为

- 两侧键 dtype **相同**（如 `int64`/`int64`、`uint64`/`uint64`、
  `Int64`/`Int64`、`UInt64`/`UInt64`）：按精确整数哈希，标识和重复次数正确，
  与行顺序、固定分区键无关。
- 两侧键一为有符号、一为无符号且**声明类型不同**（`int64`/`uint64`、
  `Int64`/`UInt64`、`UInt64`/`int64` 等）：连接索引计算会把两列协调为
  `float64` / `Float64`（`find_common_type` → `np.result_type`），超过 2^53 的
  相邻整数会落到同一个浮点值。于是
  - 不同键可能被关联（误配，多挂记录）；
  - 误配后又与真实的同键组合混在一起，重复次数被放大；
  - `left` 中本应无匹配的左行被挂到并不等于其键的右行，`right_id` 不再为空。
  - 是否立即走浮点取决于内部路径：部分组合（如右表 `UInt64`、左表 `int64`）
    在升序且唯一时经 `Index.join` 的 `object` 合成而恰好正确，但那只对特定
    行序成立，不是类型层面的保证。
- 同符号性（`int64`/`int64`、`int64`/`Int64`、`uint64`/`UInt64` 等）在本次
  用例中精确，且不受行序影响；但“小样本通过”不能外推到混合符号性。
- **顺序和固定分区键会改变结果**，因为 pandas 在单键、两表键都单调递增且至少
  一侧唯一时走 `Index.join`（索引路径），否则走因子化路径；两条路径的 dtype
  协调方式不同。以公开事故为例：
  - 单键、右表降序（非单调）：因子化把 `int64`/`uint64` 转成 `float64`，两个
    左键都挂到两个右行，输出 4 行（2 个误配）。
  - 单键、右表升序：走 `Index.join`，`int64`/`uint64` 先合成 `object`，结果正确。
  - 加固定 `part=7` 后变成两键连接，`(key, part)` 各自因子化，`key` 仍转
    `float64`，即使升序也输出 4 行。固定分区键**不能**修复，反而会触发/保留缺陷。
  - 可空 `Int64`/`UInt64`（左可空有符号、右可空无符号）组合即使升序也走
    `Index.join` 的 `Float64` 合成，结果同样错误；方向对调可能因路径不同恰好
    正确，但只是特定行序下的巧合，不能当作保证。
- `validate="one_to_one"` 只在**每侧分别**检查键列唯一性，且这一检查确实精确
  （直接使用原始键数组，不做跨表类型协调）：真实重复（含重复空键）会被拒绝。
  但它**不能**发现两表之间的误配——每侧各自唯一时，`one_to_one` 会放行，随后
  仍可能把不同的整数关联起来。因此"设置 one_to_one 且调用成功"不是身份正确的
  证据。
- 空值规则沿用 pandas：两边的空键相互匹配，非空键只与数值相等的非空键匹配；
  `left` 为每条无匹配左行保留一行、`right_id` 为空并保留左行键。
  `one_to_one` 会把同侧重复空键当作真实重复而拒绝；`validate=null` 允许重复。
- 空表、负数、`uint64` 上界（如 `18446744073709551615`）在**相同 dtype** 或
  未触发浮点协调时按精确整数处理；一旦落入上述跨符号浮点协调，同样不保证。

**结论：2.2.2 对"有符号/无符号混用"的大整数标识不保证精确身份，也不保证不受
行顺序和固定分区键影响。小整数样本通过不能作为完整整数范围的依据。**

## 二、调用方规避（本版本可用，需自行验证）

适用范围：只能改调用方、不能改 pandas，且接受以 `object` dtype 进出的代价。
原理：把两个标识列先转成 `object`（Python `int` / `None`），让 pandas 走对象
因子化，绕开浮点协调。必须显式做整数规范化和空值统一，不能只依赖 `astype(object)`。

```python
# 伪代码；两侧均适用
def normalize(series):          # object dtype, Python int or None
    return [None if pd.isna(x) else int(x) for x in series.array]

left = left.assign(key=normalize(left["key"]))
right = right.assign(key=normalize(right["key"]))
result = left.merge(right, on=(["key", "part"] if partition else ["key"]),
                    how=how, sort=False, validate=validate)
```

要点与局限：
- 规范化后的 `None` 保持契约的"空键相配"规则；两侧都要做，不能只做一侧。
- 结果键列是 `object`（Python `int`），不再是 `int64`/`uint64`；下游若依赖
  numpy dtype 需自行转回，且转回前要确认值域。
- 对 `validate="one_to_one"`，唯一性检查改为对精确 Python 整数做，真实重复
  会被拒绝，跨符号的合法唯一键不再被误判。
- 仍是"库外补丁"：依赖 pandas 对 object 键的精确行为，**不是上游保证**；
  应配合本仓库的证据用例逐条重放后再上线。
- 不要用"先排序"掩盖：排序只在单键且单调唯一时才改变走哪条路径，可空组合和
  固定 `part` 即使升序仍会误配（见 REVIEW.md RE-2/RE-3/RE-5）。

## 三、库内最小修复建议（建议，非现版本已有）

适用范围：可在 pandas 内部改动时。目标是消除"有符号/无符号混用 → 浮点"这一
协调，而不是调整调用方或依赖排序。

最小方案（伪代码）：只对**参与匹配的键数组**做精确化，不改写原表列，从而不改变
输出键 dtype。理由是与唯一性检查和输出键相关的代码已按每侧原始键精确工作；缺陷
集中在连接索引计算时的类型协调。可在 `get_join_indexers`
（`core/reshape/merge.py:1692`）入口，对"两侧均为整数、声明类型不同且符号性
不同"的键替换为 `object` 精确整数数组后再走原有单键/多键分支；单键的
`Index.join` 快路径和多键的 `_factorize_keys` 都从传入数组重建索引，因此两条
路径会一起修好。

```python
# 伪代码：放在 get_join_indexers / _factorize_keys 的数值协调处
def exactify(a):                      # a: ndarray 或整数 ExtensionArray
    if isinstance(a, ExtensionArray):
        return a.astype(object)       # 保留 Python int / pd.NA
    return a.astype(object)

if (is_integer_dtype(lk.dtype) and is_integer_dtype(rk.dtype)
        and lk.dtype != rk.dtype
        and is_unsigned_integer_dtype(lk.dtype) != is_unsigned_integer_dtype(rk.dtype)):
    lk, rk = exactify(lk), exactify(rk)
```

- 只有"必须精确"的整数键需要 object 化；相同符号性（如 `int64`/`int32`）仍走
  原有 numpy 提升，避免无谓的性能损失。
- 不要在 `_maybe_coerce_merge_keys`（`core/reshape/merge.py:1364`）里直接改写
  `self.left`/`self.right` 的键列：原型实验表明这会把输出键 dtype 变为
  `object`，破坏现有正常回归对 `key=int64` 的断言；唯一性检查本身已经是每侧
  原始键精确的，无需随匹配改动。
- 需评估：object 因子化的性能影响属于上游兼容性决策；结果键 dtype 保持不变。
  本仓库 **不实现、不提交生产修复**，此处仅给出方向与伪代码。一次性原型中，
  库内方案覆盖了 REVIEW.md 的全部证据用例且原正常回归（含 `key=int64` 断言）
  仍通过；调用方规避只保证身份正确，**输出键 dtype 会变成 `object`**，因此
  `checks.py normal` 对 `key` dtype 的断言不适用于该规避，需在调用方自行转换。

## 四、发布检查

- 只检查"异常和输出键列外观"不足：键列仍显示整数时也可能已误配。
- 必须按 `(left_id, right_id, key[, part])` 比较**多重集并忽略结果行序**，并在
  单因素对照下覆盖：重排、固定 `part`、大整数（>2^53 与跨 `int64` 上界）、
  缺失、真重复、负数与 `uint64` 上界。
- 小整数回归（`NORMAL_REGRESSION_OK`）只证明小范围路径；不能外推到完整范围。
- 行序和固定分区键不是"统一批次/键形式"的无害变换，发布前必须在两类路径
  （单调 `Index.join` 与非单调因子化）分别验证。
