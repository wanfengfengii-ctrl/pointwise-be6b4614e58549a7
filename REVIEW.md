# 整数标识关联审查（pandas 2.2.2）

审查对象：pandas `v2.2.2`（NumPy 1.26.4），入口为 `DataFrame.merge`，范围为
`inner`/`left`、`int64`/`uint64`/`Int64`/`UInt64`、`sort=False`，可选
`validate="one_to_one"` 与固定 `part=7` 分区键。生产源码、`probe.py`、
`samples.py`、`checks.py`、`source_manifest.py` 均未修改。

复现命令（三个入口均需经 `bootstrap.py`）：

```
python3 bootstrap.py checks.py normal          # 原正常回归，应输出 NORMAL_REGRESSION_OK
python3 bootstrap.py checks.py incident        # 原事故断言，应稳定失败
python3 bootstrap.py review_evidence.py run    # 生成 evidence.json
python3 bootstrap.py review_evidence.py verify # 重放并核对报告引用
python3 bootstrap.py review_evidence.py demo   # 真实正常结果 + 身份误配
```

独立期望只用输入行、Python 精确整数和契约的空值规则计算，不调用 pandas/NumPy
的关联、类型协调或因子化，也不采信原实现结果（见 `review_evidence.py:expected`）。
比较按 `(left_id, right_id, key[, part])` 多重集进行，忽略结果行序。

## 结论摘要

**发布意见：不批准按现行使用说明上线。** 2.2.2 在两侧标识为“一有符号、一无符号
且声明类型不同”时，连接索引计算会把键协调为 `float64`/`Float64`，超过 2^53 的
不同整数可能被当作同一标识，导致误配、重复次数放大和 `left` 左行错误挂接。
重排、固定分区键和可空表示都会改变走哪条内部路径，因此“排序统一批次”和“加固定
分区键”都不是安全操作；`validate="one_to_one"` 只检查每侧唯一性，放行跨表误配。
相同 dtype（`int64`/`int64`、`uint64`/`uint64`、`Int64`/`Int64`、
`UInt64`/`UInt64`）与同为有符号的混合（如 `int64`/`Int64`）在本次用例中保持
精确；这不能外推到混合符号性。

## 源码链路（模块相对路径:行号，发行包原始行号）

1. `pandas/core/frame.py:10815-10846` `DataFrame.merge` 原样转调
   `pandas.core.reshape.merge.merge`（`core/reshape/merge.py:137-184`）。
2. `core/reshape/merge.py:170` 构造 `_MergeOperation`；`__init__` 在
   `807` 调用 `_maybe_coerce_merge_keys`（定义在 `1364`），随后在 `813`
   执行 `validate` 检查（`1633` 起）。
   关键：`_maybe_coerce_merge_keys` 的数值分支在 `1474-1478` 用
   `lib.infer_dtype(lk) == lib.infer_dtype(rk)`（两边都是 `"integer"`）直接
   `continue`，**不把混合有/无符号键改成精确类型**，`left_join_keys` /
   `right_join_keys` 仍是 `int64` 与 `uint64`。
3. `core/reshape/merge.py:882-896` `get_result` → `_get_join_info`
   （`1129-1190`）→ `_get_join_indexers`（`1119-1127`）→
   `get_join_indexers`（`1692-1767`）。
4. `get_join_indexers` 的路径分叉在 `1749-1761`：
   - 若 `Index(lkey)` 与 `Index(rkey)` 都单调递增且至少一侧唯一（`1752-1756`），
     走 `Index.join`（`1757`）。
   - 否则走 `get_join_indexers_non_unique`（`1759-1761`）→
     `_factorize_keys`（`2398-2585`）→
     `_convert_arrays_and_get_rizer_klass`（`2588-2622`）。
   - 多键（`partition=true`）时 `1734-1744` 对每一层先做 `_factorize_keys`，
     因此**总是**走因子化路径，与是否单调无关。
5. 精度丢失点一（因子化）：`_convert_arrays_and_get_rizer_klass` 在
   `2593-2608` 用 `find_common_type([lk.dtype, rk.dtype])` 求共同类型；
   `pandas/core/dtypes/cast.py:1485` 落到 `np_find_common_type`，
   `cast.py:1406` 用 `np.result_type(int64, uint64) = float64`，随后
   `merge.py:2607-2608` 两侧 `astype(float64)`；可空类型经
   `pandas/core/dtypes/dtypes.py:1590-1605` 先解包 numpy dtype，同样得到
   `float64` 再重新包装为 `Float64`。
6. 精度丢失点二（索引路径）：`pandas/core/indexes/base.py:4628-4632`
   在 dtype 不同时调 `_find_common_type_compat`（`6371-6392`）。它仅把
   **numpy `uint64`** 与有符号整数的组合特判为 `object`（`6384-6388`），
   其余走 `find_result_type`（`6390`）；`UInt64`/`Int64`/`Float64` 的
   可空组合不在特判内，所以可空混合即使走索引路径仍变成 `Float64`。
   进入 dtype 比较前，`Index.join` 先调 `_maybe_downcast_for_indexing`
   （`4600-4605`，定义在 `6325`）：若左索引为无符号、右索引为有符号且右最小值
   ≥ 0，则把右索引精确转成左的无符号 dtype（`6349-6354`）。这解释了方向依赖：
   `UInt64` 左、`Int64` 右且键非负时升序可恰好正确，而 `Int64` 左、`UInt64`
   右不具备该捷径；反向或含负值时仍落入浮点协调。该捷径只依赖数据取值和
   行序，不是类型层面的保证。
7. 唯一性检查：`merge.py:1633-1643` 用 `MultiIndex.from_arrays(
   self.left_join_keys).is_unique` 逐侧检查，使用的是协调前的原始键数组，
   因而**对真实重复是精确的**，但只做“每侧各自唯一”，不校验跨表键是否相等。
   所以每侧唯一时 `one_to_one` 会放行已被误配的连接。
8. 输出键列：`_maybe_add_join_keys`（`1003-1117`）在需要填充或键列不在结果中时，
   按 `find_common_type([lvals.dtype, rvals.dtype])`（`1089`）重建键列并
   `result.insert`（`1117`）；若结果已含左侧 `key` 列且无缺失填充，则沿用左列。
   事故中输出 `key` 仍是 `int64`（沿用左列），**键列外观不能证明身份正确**。

## 根因

业务键是精确整数，但连接索引计算在混合有/无符号且声明类型不同时选择了
浮点公共类型。`float64` 只有 53 位尾数：`2^53` 与 `2^53+1`、`2^63-1` 与
`2^63`、`uint64` 上界附近的不同值会落到同一浮点值。多键连接先把每一层因子化，
再把标签组合成整数编码，所以固定 `part` 既不能修正、也无法阻止 `key` 层丢精度。
唯一性检查发生在每侧、且用原始键，能拒绝真实重复，却无法发现跨表误配。

触发边界（本次验证）：
- 触发：两侧声明类型不同、一为有符号一为无符号；任一非空键的绝对值 > 2^53
  或需要精确到超出 53 位尾数。
- 单键且两侧单调递增、至少一侧唯一时可能恰好走 `Index.join` 得到正确结果
  （numpy `int64`/`uint64` 特判为 `object`），但该结果依赖行序，不能作为保证。
- 可空 `Int64`/`UInt64`（左可空有符号、右可空无符号）即使行序升序也先在
  `Index.join` 处合成 `Float64` 并产生误配；方向对调（`UInt64`/`Int64`）升序时
  恰好正确，但同样依赖行序和内部路径，不能作为保证。
- 任一非空键超出 ±2^53 即可能出错；全部键在 ±2^53 内时浮点转换恰好精确，
  “碰巧正确”不是契约保证。

## 证据与报告定位（`evidence.json`，忽略行序比较）

每个案例保存完整 spec、完整 observation、独立 expected、differences 与
report_ref；`verify` 会重放原观察入口并逐字段核对。差异在本版本复现，而不是
要求原实现给出正确结果。RE-1 为基线，RE-2 到 RE-8 均为单因素对照（`control_of`
指向被改动前的案例）。

## RE-1：正常回归与观察基线

- `C01_normal`：`normal` 样例，`left`、`one_to_one`，输出
  `[L1,null,1]、[L2,R2,2]、[L3,R3,3]`，与独立期望一致；原
  `checks.py normal` 仍输出 `NORMAL_REGRESSION_OK`。
- `C02_empty_left`：空 `Int64` 左表 inner，输出 0 行。
- `C03_empty_right_left`：空 `Int64` 右表 left，保留左行 `UInt64` 上界，
  `right_id=null`、键 `18446744073709551615` 原样保留。
- 基线说明：小整数与空表只覆盖了“相同/精确”路径。

## RE-2：重排单因对照

- `C05_incident_right_asc`：与事故同值同侧，仅右表升序，走 `Index.join` 的
  `object` 特判，输出恰为 `[L0,R0,2^53]、[L1,R1,2^53+1]`，正确。
- `C04_incident`（`control_of=C05`）：仅把右表改成降序，走因子化路径，
  输出 4 行，新增 `[L0,R1,2^53]` 与 `[L1,R0,2^53+1]` 两个误配。
- `C06_same_dtype_reordered`：同 dtype `int64`、右表降序，输出仍正确，说明
  “重排有害”只在混合符号性时出现。
- 结论：结果依赖行序；`sort=False` 下“仅调整来源行顺序不影响匹配身份”的现行
  说明不成立。排序不能作为修复，因为可空与分区场景排序后仍错（RE-3、RE-5）。

## RE-3：固定分区键单因对照

- `C07_partition_asc`（`control_of=C05`）：C05 正确，加固定 `part=7` 后变成
  两键连接，`key` 层仍因子化为浮点，输出 4 行，误配两个。
- `C08_partition_int64_control`：同 dtype `int64` 加 `part=7`，正确，定位到
  差异来自混合符号性而非分区列本身。
- `C31_same_signedness_partition`（`control_of=C08`）：C08 把右表改为可空
  同符号 `Int64` 并保留 `part=7`，仍正确，进一步确认触发条件是“有/无符号
  混合”而不是“可空/非可空”或分区列。
- `C28_left_join_partition_misattach`（见 RE-8）：left + `part=7` 把本应无匹配的
  左行 `L1` 挂到 `R0`。
- 结论：“给两边增加同值固定分区键只改变键的形式、不会改变归属”不成立。

## RE-4：大整数边界与误配

- `C09_safe_range_unsorted`：`2^53-1` 与 `2^53`，右表降序，仍正确；说明
  ±2^53 内浮点恰好精确。
- `C10_boundary_false_match`（`control_of=C09`）：左仅 `2^53`，右含
  `2^53+1` 与 `2^53-1`，输出 `[L0,R1,2^53]` —— 把 `2^53+1` 的右行挂到
  `2^53` 左行，独立期望为 0 行。这是“凭空多挂记录”。
- `C11_int64_max_collision`：左 `int64` 上界 `2^63-1`，右 `uint64` 的
  `2^63` 与 `2^63+1` 都映射为同一浮点，输出 2 行，独立期望 0 行。
- `C12_power_of_two_exact`：`2^60`/`2^61` 可被浮点精确表示，结果正确；
  说明触发条件是“相邻不可表示”，不是单纯“数值大”。
- `C13_validate_not_protective`（`control_of=C05`）：左右键各唯一、
  `one_to_one`，右表可空 `UInt64`；`validate` 通过后仍把左 `L1`（`2^53+1`）
  挂到右 `R0`（`2^53`），输出 2 行，独立期望 1 行。
- 结论：`validate="one_to_one"` 不能作为身份正确或“完整整数范围可用”的依据。

## RE-5：缺失值与可空表示

- `C14_nullable_small`：`Int64`/`UInt64` 小整数加空键，空键相互匹配，
  非空键精确，`one_to_one` 通过，正确。
- `C15_nullable_large_desc`（`control_of=C14`）：换成 `2^53`/`2^53+1` 且右表
  降序，空值规则仍正确，但两个非空键都误配。
- `C29_nullable_asc_no_partition`（`control_of=C05`）：与 C05 同值同序，仅改为
  可空 `Int64`/`UInt64`；即使升序也走因子化并转 `Float64`，输出 4 行，
  独立期望 2 行。说明可空表示本身触发问题，与排序无关。
- `C16_nullable_partition`（`control_of=C15`）：升序 + `part=7`，仍输出 4 行。
- `C17_null_no_false_match`：空键只与空键匹配，非空键不因空值被误配，正确。
- `C18_null_duplicate_validate`：同侧两个空键 + `one_to_one`，按契约判为真实
  重复并报 `MergeError`。
- 结论：可空类型不改变空值语义，但会加重 dtype 协调问题（`Float64`）。

## RE-6：真重复与重复次数

- `C19_duplicates_small`：小整数真重复、`validate=null`，保留
  `[L0,R0,7]、[L1,R0,7]`，重复次数正确。
- `C20_duplicates_small_validate`（`control_of=C19`）：改 `one_to_one`，
  正确报 `MergeError`。
- `C21_duplicates_large_mixed`（`control_of=C19`）：换大整数与 `int64`/`uint64`
  混用、两侧升序；独立期望 4 行（两个 `2^53` 左行 × 一个 `2^53` 右行，
  两个 `2^53+1` 右行 × 一个左行），实际 9 行 —— 误配使重复次数同时放大到
  两侧全部组合。
- `C22_duplicates_large_same_dtype`（`control_of=C21`）：改为同 dtype `int64`，
  恢复 4 行，确认重复次数问题源于混合符号性而非重复本身。
- `C32_same_signedness_duplicates`（`control_of=C22`）：C22 把右表改为可空
  同符号 `Int64` 并降序，仍为 4 行，排除“可空类型本身”作为原因。
- 结论：真实重复的“保留所有左右组合”只在精确身份下成立；误配会伪造额外重复。

## RE-7：负数与无符号上界

- `C23_negative_mixed`：左 `int64` 含 `-1` 与 `0`，右 `uint64` 含上界与 `0`，
  只输出 `[L1,R1,0]`，`-1` 未与 `uint64` 上界误配（浮点符号不同，不会碰撞）。
- `C24_uint64_top_same_dtype`：`uint64` 上界同 dtype 匹配，精确。
- `C25_uint64_vs_signed_no_wrap`：`uint64` 上界对 `int64` 上界，输出 0 行，
  未发生无符号回绕成负数。
- `C26_signed_min_same_dtype`：`int64` 下界同 dtype 精确。
- 结论：本次未发现负数跨符号误配，但混合符号性仍走浮点；不能据此宣布负数
  “安全”，修复也不应依赖符号差。无符号上界在同 dtype 下正确。

## RE-8：左连接保留与组合

- `C27_left_join_ordered`：左 `2^53`、`2^53+1`，右仅 `2^53`，升序；
  输出 `[L0,R0,2^53]` 与 `[L1,null,2^53+1]`，未匹配左行保留、键保留，正确。
- `C30_left_join_right_desc`（`control_of=C27`）：仅右表降序，输出 4 行，
  `L1` 被挂到 `R0`，`right_id` 不再是空。
- `C28_left_join_partition_misattach`（`control_of=C27`）：仅加 `part=7`，
  同样把 `L1` 挂到 `R0`，独立期望含一行 `[L1,null,2^53+1,7]`。
- 结论：左连接“无匹配保留一次”只在精确路径成立；重排与固定分区键都会破坏它。

## 调用方规避 vs 库内最小修复

两者都只在说明中给出伪代码，未修改生产实现。原型验证（一次性进程内 monkeypatch，
不写入源码）显示：下方库内方案对本文 32 个案例全部匹配独立期望，且
`checks.py normal` 仍输出 `NORMAL_REGRESSION_OK`。

| 维度 | 调用方规避：键列转 `object` Python 整数 | 库内最小修复：索引计算前精确化键数组 |
| --- | --- | --- |
| 位置 | 调用方 `merge` 之前 | `merge.py:1692` `get_join_indexers` 入口（或 `_factorize_keys` 协调处） |
| 做法 | 两侧键规范化为 `None`/`int`，`object` dtype 后 merge | 仅当两侧整数且符号性不同时，把传入键数组 `astype(object)` 再走原路径 |
| 覆盖路径 | 同时绕开索引路径和因子化路径 | 单键 `Index.join` 与多键因子化同时修复 |
| 输出键 dtype | 变为 `object`（下游需自行转回） | 保持不变（原表列与输出键未被改写） |
| 空值 | 需显式 `None` 统一，否则 `pd.NA` 与 `None` 可能不一致 | 沿用原有缺失处理 |
| 唯一性 | 对 Python 整数精确，真实重复仍拒绝 | `validate` 本已按每侧原始键精确，无需改动 |
| 风险 | 依赖 object 键行为，非上游保证；结果 dtype 变化 | 需上游评估 object 因子化性能与 API 兼容性 |
| 适用 | 不能改 pandas、可接受 dtype 变化 | 可在 pandas 内部修复时 |

不得以排序掩盖：排序只在“单键、两侧单调、至少一侧唯一”时改变路径，可空混合
（C29）和固定分区（C07/C16）即使升序仍误配；这是路径选择问题，不是顺序问题。

故障可用于灰度判据的最小修复方向：

- 只对“有符号性不同”的整数键 object 化，相同符号性（如 `int64`/`int32`、
  `int64`/`Int64`）保持原有提升；
- 不在 `_maybe_coerce_merge_keys` 里改写 `self.left`/`self.right` 键列，否则
  会把输出键 dtype 变成 `object` 并破坏现有 `key=int64` 回归；
- 需同时覆盖单键、多键、可空与 `left` 未匹配保留。

## 发布意见

1. **阻断**：混合有/无符号整数标识、且可能出现 |key| > 2^53 时，2.2.2 的
   `merge` 不保证精确身份，也不保证重排与固定分区键前后等价；不得按现行说明
   在生产上线。
2. **现行说明已修订**：`docs/integer-merge.md` 已把“当前实际行为”“调用方规避”
   “库内建议”分开，删除“排序/固定分区键无害”“检查异常和键列外观即可”
   “小样本通过即可用于完整范围”等错误保证，并注明建议并非现版本已提供。
3. **放行条件**（任一）：
   - 只使用相同 dtype（含同符号性），并在发布检查中按多重集对照覆盖重排、分区、
     大整数、缺失与真重复；或
   - 采用调用方 `object` 精确化规避，并逐条重放本仓库证据；或
   - 上游按上述最小修复落地并发布通过相同证据的版本。
4. **不可接受的替代**：排序、加固定分区键、只看 `key` 列显示整数、
   仅依赖 `validate="one_to_one"` 或小整数回归通过。
5. 公开事故 `checks.py incident` 仍按契约稳定失败（`MERGE_IDENTITY_MISMATCH`），
   本次审查不要求它变为通过，也没有修改生产源码或原回归。
