"""Restore V2.1 code only; dry run by default, preserving dossiers and later work."""
from pathlib import Path
from datetime import datetime, UTC
from hashlib import sha256
from zipfile import ZipFile
import argparse
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    audit=ROOT/'data/v3_audit';archive=audit/'before_v3_code.zip'
    baseline=json.loads((audit/'baseline.json').read_text(encoding='utf-8'))
    if sha256(archive.read_bytes()).hexdigest()!=baseline['code_archive_sha256']:raise ValueError('Respaldo V2.1 alterado')
    before={r['path']:r['sha256'] for r in json.loads((audit/'before_v3_manifest.json').read_text(encoding='utf-8'))}
    release=json.loads((audit/'release_manifest.json').read_text(encoding='utf-8'))
    rows=[r for r in release['files'] if r['status']!='unchanged']
    for row in rows:
        target=(ROOT/row['path']).resolve()
        if not target.is_relative_to(ROOT) or target.relative_to(ROOT).parts[0] in ('projects','data','output','ENTREGAS'):
            raise ValueError('Ruta fuera del alcance de reversión de código')
        if not target.exists() or sha256(target.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Hay trabajo posterior. Conserve y concilie antes de revertir: '+row['path'])
    with ZipFile(archive) as backup:
        for name,digest in before.items():
            if sha256(backup.read(name)).hexdigest()!=digest:raise ValueError('Contenido del respaldo alterado: '+name)
        print('Archivos de código a restaurar o archivar:',len(rows))
        if not args.apply:
            for row in rows:print(row['status'],row['path'])
            print('Simulación: ningún archivo modificado. Detenga el servidor antes de usar --apply.')
            return
        saved=audit/('before_rollback_'+datetime.now(UTC).strftime('%Y%m%dT%H%M%S%f'));saved.mkdir()
        for row in rows:
            dest=saved/row['path'];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/row['path'],dest)
        for row in rows:
            target=ROOT/row['path']
            if row['path'] in before:target.write_bytes(backup.read(row['path']))
            else:target.unlink()
    print('Código V2.1 restaurado. Documentos, revisiones y exportaciones conservados.')
    print('Metadatos workflow de V3 conservados; V2.1 no los muestra. Archivo de código V3:',saved)
    print('Las aprobaciones V3 requieren revisión al usar código anterior. No se migran a la fuerza.')


if __name__=='__main__':main()
