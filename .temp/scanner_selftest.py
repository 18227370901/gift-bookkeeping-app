import sys
sys.path.insert(0, r"C:\Users\cheng\Documents\akshare-test\gift_bookkeeping_app\.temp")
import scan_fstring_compat as s

# 3.11 不兼容样例：f-string 表达式内用与外层相同的双引号取字典 key
bad1 = 'print(f"{d["k"]}")'
# 3.11 兼容样例：表达式内用单引号
good1 = "print(f\"{d['k']}\")"
# 3.11 不兼容样例：嵌套 f-string 且内层用相同引号
bad2 = 'x = f"{f"{a}"}"'
# 兼容样例：三引号外层
good2 = 'x = f"""{d["k"]}"""'

for name, src, expect in [
    ("bad1", bad1, True),
    ("good1", good1, False),
    ("bad2", bad2, True),
    ("good2", good2, False),
]:
    fs, err = s.get_fstring_segments(src)
    if err:
        print(f"{name}: tokenize err {err}")
        continue
    hit = False
    for line_no, raw, delim, content in fs:
        probs = s.check_expression_quotes(content, delim)
        if probs:
            hit = True
    status = "PASS" if hit == expect else "FAIL"
    print(f"{status} | {name}: src={src!r} expect_problem={expect} detected={hit}")
