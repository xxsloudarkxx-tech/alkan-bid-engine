"""Verified code rollback to V2. Dry run by default; never removes project data."""
from datetime import datetime, UTC
from hashlib import sha256
from pathlib import Path
import argparse
import json
import shutil
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    audit=ROOT/'data/v21_audit';baseline=json.loads((audit/'baseline.json').read_text(encoding='utf-8'))
    archive=audit/'before_v21_code.zip'
    if sha256(archive.read_bytes()).hexdigest()!=baseline['code_archive_sha256']:raise ValueError('Respaldo alterado')
    release=json.loads((audit/'release_manifest.json').read_text(encoding='utf-8'))
    rows=[r for r in release['files'] if r['status']!='unchanged']
    for row in rows:
        path=(ROOT/row['path']).resolve()
        if not path.is_relative_to(ROOT) or path.relative_to(ROOT).parts[0] in ('projects','output','ENTREGAS','data'):
            raise ValueError('Ruta fuera del alcance de reversión de código')
        if not path.exists() or sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Cambios posteriores: concilie antes de revertir '+row['path'])
    with ZipFile(archive) as backup:
        originals={r['path']:r['sha256'] for r in json.loads((audit/'before_v21_manifest.json').read_text(encoding='utf-8'))}
        for name,digest in originals.items():
            if sha256(backup.read(name)).hexdigest()!=digest:raise ValueError('Archivo de respaldo alterado: '+name)
        print('Archivos de código afectados:',len(rows))
        if not args.apply:
            for row in rows:print(row['status'],row['path'])
            print('Simulación. Detenga el servidor local antes de usar --apply. Expedientes conservados.')
            return
        saved=audit/('before_rollback_'+datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f'));saved.mkdir()
        # Archive every changed file before restoring any of them.
        for row in rows:
            path=ROOT/row['path'];dest=saved/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,dest)
        for row in rows:
            path=ROOT/row['path']
            if row['path'] in originals:path.write_bytes(backup.read(row['path']))
            else:path.unlink()
    print('Código V2 restaurado; documentos, revisiones, precios, costos y exportaciones conservados.')
    print('V2 no muestra los campos nuevos de V2.1; conserve el archivo previo a la reversión:',saved)


if __name__=='__main__':main()
