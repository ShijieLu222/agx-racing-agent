"""Reproducible minimal racing ZIP; never includes credentials or logs."""
import ast
import hashlib
from pathlib import Path
import zipfile
from validate_design import strict_json, validate

ROOT = Path(__file__).resolve().parents[1]
FILES = ('agent.py', 'track_data.py', 'track_parkland.py', 'track_highland.py',
         'track_crossover.py', 'design.json')


def pack(root=ROOT, output=None):
    root = Path(root)
    output = Path(output) if output else root / 'dist/agx-racing-agent.zip'
    validate(strict_json(root / 'design.json'))
    contents = {}
    for name in FILES:
        payload = (root / name).read_bytes()
        if len(payload) > 256 * 1024:
            raise ValueError(name + ' exceeds source size limit')
        if name.endswith('.py'):
            ast.parse(payload.decode('utf-8'), filename=name)
        contents[name] = payload
    if sum(map(len, contents.values())) > 1024 * 1024:
        raise ValueError('Total source/design size limit exceeded')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in contents.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 11, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return output, digest


if __name__ == '__main__':
    path, digest = pack()
    print(f'Bundle: {path}\nSHA256: {digest}\nContents: {", ".join(FILES)}')
