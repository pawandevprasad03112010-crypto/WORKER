import os
import json
from decimal import Decimal
import boto3
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI()

# आपके AWS और DynamoDB क्रेडेंशियल्स
AWS_ACCESS_KEY_ID = "AKIA32VVAONMQV5QKNED"
AWS_SECRET_ACCESS_KEY = "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"
REGION = "ap-south-1"
TABLE_NAME = "LARGE_PROPERTY_LISTING"
PRIMARY_KEY = "property_id"

def clean_and_convert_data(obj):
    """ None वैल्यूज़ को हटाना और float को Decimal में बदलना ताकि DynamoDB एक्सेप्ट करे """
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

def find_property_id(obj, target_key):
    """ नेस्टेड लिस्ट या डिक्शनरी के अंदर से property_id ढूंढने का रिकर्सिव फंक्शन """
    if isinstance(obj, dict):
        if target_key in obj and obj[target_key] is not None:
            return str(obj[target_key])
        for k, v in obj.items():
            result = find_property_id(v, target_key)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = find_property_id(item, target_key)
            if result:
                return result
    return None

def extract_main_dict(obj):
    """ नेस्टेड लिस्ट में से मुख्य डिक्शनरी ढूंढकर बाहर निकालना """
    if isinstance(obj, dict):
        return obj
    elif isinstance(obj, list):
        for item in obj:
            res = extract_main_dict(item)
            if res:
                return res
    return None

@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="hi">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Only Broker - Live DynamoDB Uploader</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100 min-h-screen font-sans">
    <div class="container mx-auto px-4 py-8 max-w-5xl pb-24">
        <header class="bg-white shadow rounded-lg p-6 mb-8 text-center">
            <h1 class="text-3xl font-bold text-gray-800">Only Broker - लाइव DynamoDB बल्क अपलोडर</h1>
            <p class="text-gray-600 mt-2">अपनी सभी JSON फाइलें एक साथ चुनें और लाइन-बाय-लाइन लाइव अपलोड होते हुए देखें।</p>
        </header>

        <div class="bg-white shadow rounded-lg p-8 mb-6 max-w-xl mx-auto">
            <div class="space-y-4">
                <label class="block text-lg font-medium text-gray-700">अपनी सभी JSON फाइलें चुनें (.json)</label>
                <input type="file" id="json-files" name="files" accept=".json" multiple class="block w-full text-sm text-gray-500 file:mr-4 file:py-2 file:px-4 file:rounded-full file:border-0 file:text-sm file:font-semibold file:bg-purple-50 file:text-purple-700 hover:file:bg-purple-100">
                
                <button onclick="startLiveUpload()" id="upload-btn" class="w-full bg-green-600 text-white font-bold py-3 px-4 rounded-lg hover:bg-green-700 transition shadow-lg">डेटाबेस में लाइव अपलोड शुरू करें</button>
            </div>
        </div>

        <div id="status-section" class="hidden bg-white shadow rounded-lg p-6">
            <div class="flex justify-between items-center mb-4 border-b pb-3">
                <h2 class="text-xl font-bold text-gray-800">लाइव अपलोड प्रोग्रेस</h2>
                <span id="counter-badge" class="bg-purple-100 text-purple-800 font-bold px-4 py-1 rounded-full text-sm">कुल फाइलें: 0</span>
            </div>

            <div id="file-list-container" class="space-y-2 max-h-[500px] overflow-y-auto pr-2">
            </div>
        </div>
    </div>

    <script>
        async function startLiveUpload() {
            const fileInput = document.getElementById('json-files');
            if (fileInput.files.length === 0) {
                alert('कृपया पहले कम से कम एक JSON फाइल चुनें!');
                return;
            }

            const files = fileInput.files;
            const container = document.getElementById('file-list-container');
            const statusSection = document.getElementById('status-section');
            const counterBadge = document.getElementById('counter-badge');
            const uploadBtn = document.getElementById('upload-btn');

            container.innerHTML = '';
            statusSection.classList.remove('hidden');
            uploadBtn.disabled = true;
            uploadBtn.classList.add('opacity-50');
            counterBadge.textContent = `कुल फाइलें: ${files.length}`;

            const fileRows = [];
            for (let i = 0; i < files.length; i++) {
                const file = files[i];
                const rowId = `file-row-${i}`;
                container.innerHTML += `
                    <div id="${rowId}" class="flex items-center justify-between p-3 bg-gray-50 border rounded-lg text-sm">
                        <div class="truncate w-1/2 font-mono text-gray-700">${file.name}</div>
                        <div class="text-xs text-gray-500 property-id-text">ID: स्कैन हो रहा है...</div>
                        <div class="status-badge px-3 py-1 rounded text-xs font-bold bg-yellow-100 text-yellow-800">पेंडिंग...</div>
                    </div>
                `;
                fileRows.push({ file, rowId });
            }

            for (let i = 0; i < fileRows.length; i++) {
                const { file, rowId } = fileRows[i];
                const rowElement = document.getElementById(rowId);
                const statusBadge = rowElement.querySelector('.status-badge');
                const idText = rowElement.querySelector('.property-id-text');

                statusBadge.className = "status-badge px-3 py-1 rounded text-xs font-bold bg-blue-100 text-blue-800 animate-pulse";
                statusBadge.textContent = "अपलोड हो रहा है...";

                try {
                    const formData = new FormData();
                    formData.append('file', file);

                    const response = await fetch('/upload-single', {
                        method: 'POST',
                        body: formData
                    });

                    const result = await response.json();

                    if (response.ok) {
                        idText.textContent = `ID: ${result.property_id}`;
                        statusBadge.className = "status-badge px-3 py-1 rounded text-xs font-bold bg-green-100 text-green-800";
                        statusBadge.textContent = "सफल ✔";
                    } else {
                        statusBadge.className = "status-badge px-3 py-1 rounded text-xs font-bold bg-red-100 text-red-800";
                        statusBadge.textContent = "विफल ✖";
                        idText.textContent = `एरर: ${result.detail || 'अज्ञात'}`;
                    }
                } catch (err) {
                    statusBadge.className = "status-badge px-3 py-1 rounded text-xs font-bold bg-red-100 text-red-800";
                    statusBadge.textContent = "त्रुटि ✖";
                    idText.textContent = `एरर: नेटवर्क समस्या`;
                }
            }

            uploadBtn.disabled = false;
            uploadBtn.classList.remove('opacity-50');
            alert('सभी फाइलों का लाइव अपलोड प्रोसेस पूरा हो गया है!');
        }
    </script>
</body>
</html>"""

@app.post("/upload-single")
async def upload_single(file: UploadFile = File(...)):
    try:
        content = await file.read()
        
        try:
            raw_data = json.loads(content.decode('utf-8'))
        except Exception as json_err:
            raise HTTPException(status_code=400, detail="Invalid JSON format in file")
        
        # 1. नेस्टेड स्ट्रक्चर से property_id ढूंढना
        prop_id = find_property_id(raw_data, PRIMARY_KEY)
        if not prop_id:
            # अन्य संभावित की (Keys) से भी चेक करना
            for alt_key in ["id", "propertyId", "serial_no"]:
                prop_id = find_property_id(raw_data, alt_key)
                if prop_id:
                    break

        if not prop_id:
            raise HTTPException(status_code=400, detail="JSON file does not contain property_id")

        # 2. डेटा को सही डिक्शनरी फॉर्मेट में निकालना ताकि DynamoDB में सेव हो सके
        main_dict = extract_main_dict(raw_data)
        if not main_dict:
            raise HTTPException(status_code=400, detail="Invalid JSON data structure")

        # सुनिश्चित करना कि डिक्शनरी में property_id सेट हो
        main_dict[PRIMARY_KEY] = str(prop_id)

        cleaned_data = clean_and_convert_data(main_dict)

        dynamodb = boto3.resource(
            'dynamodb',
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
            region_name=REGION
        )
        table = dynamodb.Table(TABLE_NAME)
        table.put_item(Item=cleaned_data)

        return {"success": True, "property_id": str(prop_id), "filename": file.filename}

    except Exception as ex:
        print(f"❌ Error uploading {file.filename}: {str(ex)}")
        raise HTTPException(status_code=400, detail=str(ex))
        
