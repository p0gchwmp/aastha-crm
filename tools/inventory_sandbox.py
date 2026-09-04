#!/usr/bin/env python3
"""Development adapter that simulates external Inventory consumption."""
import json, os, sys, urllib.request, urllib.error, uuid
BASE=os.getenv("AASTHA_API","http://localhost:8000/api/v1")
KEY=os.getenv("INVENTORY_KEY","dev-inventory-key")

def request(method,path,body=None):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(BASE+path,data=data,method=method,headers={"Content-Type":"application/json","X-Integration-Key":KEY})
    with urllib.request.urlopen(req) as r:return json.load(r)

def main():
    events=request("GET","/external/procedures/inventory-events")
    if not events:
        print("No pending Inventory events.");return
    for event in events:
        p=event["payload"]
        print("Consume stock for",p.get("service_code"),"at rendering branch",p["rendering_branch_id"],"execution",p["procedure_execution_id"])
        request("POST",f"/external/procedures/inventory-events/{event['event_id']}/ack",{"external_event_id":f"INV-ACK-{uuid.uuid4()}"})

if __name__=="__main__":
    try:main()
    except urllib.error.HTTPError as e:
        print(e.code,e.read().decode(),file=sys.stderr);sys.exit(1)
