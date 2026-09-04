#!/usr/bin/env python3
"""Tiny development adapter that simulates a separate Procedure Finance system.

It polls Procedure Order outbox events, reads the order contract, sends CLEARED,
and acknowledges the event. Uses only Python stdlib.
"""
import json, os, sys, urllib.request, urllib.error, uuid

BASE=os.getenv("AASTHA_API","http://localhost:8000/api/v1")
KEY=os.getenv("PROCEDURE_FINANCE_KEY","dev-procedure-finance-key")


def request(method,path,body=None):
    data=None if body is None else json.dumps(body).encode()
    req=urllib.request.Request(BASE+path,data=data,method=method,headers={"Content-Type":"application/json","X-Integration-Key":KEY})
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    events=request("GET","/external/procedures/finance-events")
    if not events:
        print("No pending Procedure Finance events.")
        return
    for event in events:
        event_id=event["event_id"]
        event_type=event["event_type"]
        order_id=event["payload"]["procedure_order_id"]
        if event_type=="PROCEDURE_ORDER_CREATED":
            order=request("GET",f"/external/procedures/orders/{order_id}")
            print("Billing order:",order["patient"]["uhid"],order["service"]["name"])
            callback={
                "external_event_id":f"FIN-{uuid.uuid4()}",
                "financial_status":"CLEARED",
                "external_reference":f"PF-{str(uuid.uuid4())[:8].upper()}",
            }
            print("Clearance:",request("POST",f"/external/procedures/orders/{order_id}/financial-status",callback))
        elif event_type=="PROCEDURE_ORDER_CANCELLED":
            print("Finance received order cancellation:",order_id,event["payload"].get("reason"))
        request("POST",f"/external/procedures/finance-events/{event_id}/ack",{"external_event_id":f"ACK-{uuid.uuid4()}"})

if __name__=="__main__":
    try: main()
    except urllib.error.HTTPError as e:
        print(e.code,e.read().decode(),file=sys.stderr);sys.exit(1)
