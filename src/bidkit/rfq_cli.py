"""JSON interface with actionable errors and operation records."""
import argparse
import os
from datetime import datetime, timezone
import json
from pathlib import Path
from .rfq_tools import NAMES, TOOLS, schemas, invoke, ToolInputError

def record_operation(path,name,data,result):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    record={'at':datetime.now(timezone.utc).isoformat(),'tool':name,'input':data,'result':result}
    encoded=(json.dumps(record,ensure_ascii=False,sort_keys=True)+'\n').encode('utf-8')
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
    try:
        if os.write(fd,encoded)!=len(encoded): raise OSError('Registro incompleto')
        os.fsync(fd)
    finally: os.close(fd)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('herramienta',choices=(*NAMES,'esquemas'))
    parser.add_argument('--input',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--registro',type=Path,default=Path('data/rfq_operations.jsonl'))
    args=parser.parse_args(argv);data={}
    try:
        if args.herramienta=='esquemas': result=schemas()
        else:
            if args.input is None: raise ToolInputError(args.herramienta,'--input','Indique archivo JSON de entrada')
            data=json.loads(args.input.read_text(encoding='utf-8-sig'))
            if args.herramienta=='rasterizar_pagina' and args.output is None: raise ToolInputError(args.herramienta,'--output','Indique ruta PNG de salida')
            result=invoke(args.herramienta,data)
            if args.herramienta=='rasterizar_pagina':
                args.output.parent.mkdir(parents=True,exist_ok=True);result.save(args.output);result={'ruta':str(args.output)}
        raw=json.dumps(result,ensure_ascii=False,indent=2)
        if args.output and args.herramienta!='rasterizar_pagina':
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(raw,encoding='utf-8')
        if args.herramienta!='esquemas': record_operation(args.registro,args.herramienta,data,result)
        print(raw)
        return 2 if isinstance(result,dict) and result.get('estado')=='BLOQUEADO' else 0
    except (ToolInputError,OSError,ValueError) as exc:
        detail=exc.data() if isinstance(exc,ToolInputError) else {'codigo':'ENTRADA_INVALIDA','herramienta':args.herramienta,'campo':'archivo' if isinstance(exc,OSError) else 'JSON','mensaje':str(exc)}
        parser.exit(2,json.dumps({'error':detail},ensure_ascii=False)+'\n')

if __name__=='__main__':raise SystemExit(main())
