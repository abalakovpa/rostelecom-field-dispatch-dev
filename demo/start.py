"""Local map demonstration. Not the team's production API or planner."""
import argparse
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8083)
    args=parser.parse_args()
    # Do not load the root .env or connect to the team's database.
    os.environ['DATA_SOURCE']='demo'
    sys.path.insert(0,str(ROOT/'demo/backend'))
    import uvicorn
    print('DEMO ONLY: file inputs and in-memory plans; team API is Fastify.',flush=True)
    uvicorn.run('api.main:app',host='127.0.0.1',port=args.port)

if __name__=='__main__':main()
