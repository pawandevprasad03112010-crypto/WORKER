import os
import json
from decimal import Decimal
import boto3
from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Aapke AWS aur DynamoDB credentials
AWS_ACCESS_KEY_ID = "AKIA32VVAONMQV5QKNED"
AWS_SECRET_ACCESS_KEY = "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"
REGION = "ap-south-1"
TABLE_NAME = "LARGE_PROPERTY_LISTING"
PRIMARY_KEY = "property_id"

def clean_and_convert_data(obj):
    """ None values ko hatana aur float ko Decimal mein badalna taaki DynamoDB accept kare """
    if isinstance(obj, list):
        return [clean_and_convert_data(v) for v in obj if v is not None]
    elif isinstance(obj, dict):
        return {str(k): clean_and_convert_data(v) for k, v in obj.items() if v is not None and v != ""}
    elif isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, int):
        return int(obj)
    else:
        return str(obj) if isinstance(obj, str) else obj

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload-single")
async def upload_single(file: UploadFile = File(...)):
    try:
        content = await file.read()
        
        try:
            raw_data = json.loads(content.decode('utf-8'))
        except Exception as json_err:
            raise HTTPException(status_code=400, detail="Invalid JSON format in file")
        
        # Yadi JSON root list hai (jaise [...]), toh uska pehla dictionary item lein
        if isinstance(raw_data, list):
            if len(raw_data) > 0 and isinstance(raw_data[0], dict):
                data = raw_data[0]
            else:
                raise HTTPException(status_code=400, detail="Empty or invalid JSON list")
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            raise HTTPException(status_code=400, detail="Unsupported JSON structure")

        # JSON file ke andar se original property_id uthana
        prop_id = data.get(PRIMARY_KEY)
        
        if not prop_id:
            raise HTTPException(status_code=400, detail="JSON file does not contain property_id")
            
        # Data cleaning
        cleaned_data = clean_and_convert_data(data)

        # DynamoDB connection aur save karna
        dynamodb = boto3.resource(
            'dynamodb',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=REGION
        )
        table = dynamodb.Table(TABLE_NAME)
        table.put_item(Item=cleaned_data)

        print(f"Successfully uploaded Property ID: {prop_id} to {TABLE_NAME}")
        return {"success": True, "property_id": str(prop_id), "filename": file.filename}

    except Exception as ex:
        print(f"❌ Error uploading {file.filename}: {str(ex)}")
        raise HTTPException(status_code=400, detail=str(ex))
        
