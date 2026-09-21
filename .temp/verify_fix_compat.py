# 验证修复写法在 Python 3.6~3.11 全系可编译（3.6 语法规则与 3.11 一致）
# 坏写法（3.12 only）: f'...{', '.join(filenames)}...'
# 修复写法（全版本兼容）: f"...{', '.join(filenames)}..."
import sys
print("Python:", sys.version.split()[0])

bad = "f'x:{" + "chr(39) test" + "}'"  # 占位说明，实际用文件方式测
# 直接用文件内嵌真实片段测试
bad_src = "s = f'{a}', '.join"  # 会被 3.6 拒绝（作为对照，仅测编译器行为存在性）

fix1 = 's = f"a: {\', \'.join(filenames)} b"'          # 外层改双引号
fix2 = 's = "a: " + ", ".join(filenames) + " b"'        # 拼接替代 f-string

for name, src in [("fix1", fix1), ("fix2", fix2)]:
    try:
        compile(src, name, "exec")
        print(f"PASS | {name} 在 {sys.version.split()[0]} 可编译: {src}")
    except SyntaxError as e:
        print(f"FAIL | {name}: {e}")

# 对照组：坏写法在 3.12 可编译（证明问题只在 3.11-）
bad_real = "s = f'{', '.join(x)}'"
try:
    compile(bad_real, "bad", "exec")
    print(f"PASS(对照) | 坏写法在 {sys.version.split()[0]} (3.12) 可编译——这就是服务器报错却本地无恙的原因")
except SyntaxError as e:
    print(f"信息(对照) | 坏写法在 {sys.version.split()[0]} 也被拒: {e}")
