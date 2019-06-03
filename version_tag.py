import re
import subprocess

current_branch = (
    subprocess.check_output(["git", "symbolic-ref", "--short", "HEAD"]).decode().strip()
)
if current_branch not in ["develop", "master"]:
    exit()

object_module_text = open(
    "src/KonturSverka/Ext/ObjectModule.bsl", "r", encoding="utf-8"
).read()
result = re.search(r'Возврат "(\d+\.\d+\.\d+\.\w+)";', object_module_text)
if not result:
    raise Exception("version not found in ObjectModule.bsl")
version = result.group(1)

version = "/".join(version.rsplit(".", 1))

tag_result = subprocess.check_output(["git", "tag", "-f", version])
print(f"tagged version {version}")
