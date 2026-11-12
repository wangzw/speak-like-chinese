#!/bin/sh
# zh_check.py 的回归测试：对本目录下每个 .md 样例运行脚本，和同名的 .expected 比对。
#
# 用法：不带参数运行时做比对。全部一致时输出“全部通过”，退出码 0；否则打印 diff，退出码 1。
#       加 --update 参数运行时用当前输出覆盖 .expected，覆盖后要逐个核对改动是否符合预期。
#
# 输出第一行的文件路径只保留文件名，样例目录换了位置也能比对。
# 退出码另外核对：输出里有“硬命中：无”且没有“错误：”时应为 0，否则应为 1。

dir=$(dirname "$0")
script="$dir/../zh_check.py"
update=0
[ "${1:-}" = "--update" ] && update=1

work=$(mktemp -d) || exit 1
trap 'rm -rf "$work"' EXIT

fail=0
total=0

python3 -I "$script" > /dev/null 2>&1
status=$?
if [ "${status}" -ne 2 ]; then
  echo "不带参数时退出码应为 2，实际为 ${status}"
  fail=$((fail + 1))
fi

for sample in "$dir"/*.md; do
  [ -f "$sample" ] || continue
  total=$((total + 1))
  name=$(basename "$sample" .md)
  expected="${sample%.md}.expected"

  python3 -I "$script" "$sample" > "$work/raw" 2>&1
  status=$?
  sed 's#^===== .*/\([^/]*\) =====$#===== \1 =====#' "$work/raw" > "$work/actual"

  if grep -q '^硬命中：无$' "$work/actual" && ! grep -q '^错误：' "$work/actual"; then
    want=0
  else
    want=1
  fi
  if [ "${status}" -ne "$want" ]; then
    echo "${name}：退出码应为 ${want}，实际为 ${status}"
    fail=$((fail + 1))
  fi

  if [ "$update" -eq 1 ]; then
    cp "$work/actual" "$expected"
    continue
  fi
  if [ ! -f "$expected" ]; then
    echo "${name}：缺少预期输出文件"
    fail=$((fail + 1))
    continue
  fi
  if ! diff -u "$expected" "$work/actual" > "$work/diff"; then
    echo "${name}：输出和预期不一致"
    cat "$work/diff"
    fail=$((fail + 1))
  fi
done

if [ "$update" -eq 1 ]; then
  echo "已更新 ${total} 个预期输出，请逐个核对改动。"
fi
if [ "$fail" -eq 0 ]; then
  [ "$update" -eq 1 ] || echo "全部通过（${total} 个样例）"
  exit 0
fi
echo "有 ${fail} 处不一致（共 ${total} 个样例）"
exit 1
