import sys
sys.path.insert(0, ".")
from token_counter import count, has_tokenizer
print(f"Tokenizer: {has_tokenizer()}")
t = "你好，帮我写一个Python脚本"
print(f"{repr(t)}: {count(t)} tokens")
t2 = "Hello world"
print(f"{repr(t2)}: {count(t2)} tokens")
# Test JSON message
import json
msg = json.dumps({"role":"user","content":"帮我写一个处理CSV的Python脚本"}, ensure_ascii=False)
print(f"JSON msg: {count(msg)} tokens ({len(msg)} chars)")
