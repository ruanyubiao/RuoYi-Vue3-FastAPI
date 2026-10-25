from pathlib import Path
b = Path(r"E:\plat\PayloadGroundTest\ruoyi-fastapi-hil\hil\browser\pages.py").read_bytes()
fg = "".join(map(chr, [0x8986, 0x76d6])).encode()  # 覆盖
assert fg in b, "missing 覆盖"
print("patch ok: 覆盖 present")
