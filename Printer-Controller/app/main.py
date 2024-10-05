import asyncio
from fastapi import FastAPI, HTTPException, Request, WebSocket
import requests
from pydantic import BaseModel
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import logging
from fastapi.responses import StreamingResponse


# Initialize FastAPI app
app = FastAPI()

logging.basicConfig(level=logging.INFO)

account_sid = ''  # Deleted for privacy
auth_token = ''     # Deleted for privacy
twilio_phone_number = ''                # Deleted for privacy
twilio_whatsapp_number = ''    # Deleted for privacy

client = Client(account_sid, auth_token)

# OctoPrint API Key and Base URL (replace with your OctoPrint URL)
OCTOPRINT_API_KEY = ""                  # Deleted for privacy
OCTOPRINT_URL = "i"                            # Deleted for privacy
OCTOPRINT_WEBCAM_URL = ""   # Deleted for privacy

# Headers for the OctoPrint API request
HEADERS = {
    "X-Api-Key": OCTOPRINT_API_KEY
}

# Model for temperature control input|
class TemperatureControl(BaseModel):
    hotend_temp: float = None  # Hotend target temperature (optional)
    bed_temp: float = None     # Bed target temperature (optional)

class PrinterState(BaseModel):
    state: str
    temperature: dict

# Request body model for SMS
class SMSRequest(BaseModel):
    to: str
    message: str

class WhatsAppMessage(BaseModel):
    to: str
    message: str

# Model for movement control input
class MovementControl(BaseModel):
    x: float = None  # Distance to move on the X-axis (optional)
    y: float = None  # Distance to move on the Y-axis (optional)
    z: float = None  # Distance to move on the Z-axis (optional)
    e: float = None  # Distance to extrude on the E-axis (optional)
    speed: float = None  # Optional speed for the movement (feedrate)

def get_camera_frame():
    """
    Fetches a single frame (JPEG) from the MJPEG stream.
    Parses the multipart/x-mixed-replace stream and returns the frame as bytes.
    """
    try:
        # Open the MJPEG stream from the camera
        response = requests.get(OCTOPRINT_WEBCAM_URL, stream=True)
        
        # Ensure we have a successful response
        if response.status_code != 200:
            raise Exception(f"Unable to connect to the camera stream. Status code: {response.status_code}")
        
        # Create a boundary marker based on the Content-Type (it usually contains boundary info)
        boundary = response.headers['Content-Type'].split("boundary=")[-1]
        delimiter = f"--{boundary}"
        
        # Initialize the response iterator
        buffer = b""
        for chunk in response.iter_content(chunk_size=1024):
            buffer += chunk
            
            # Check if we've reached the end of the current frame (boundary)
            if delimiter.encode() in buffer:
                # Extract the JPEG frame (everything between two boundaries)
                frame_start = buffer.find(b'\xff\xd8')  # JPEG start marker
                frame_end = buffer.find(b'\xff\xd9')    # JPEG end marker
                
                if frame_start != -1 and frame_end != -1:
                    # Extract the complete JPEG image
                    frame = buffer[frame_start:frame_end + 2]
                    buffer = buffer[frame_end + 2:]  # Move to the next part of the stream
                    return frame
    except Exception as e:
        print(f"Error fetching frame: {e}")
        return None

@app.get("/printer", response_model=PrinterState)
def get_printer_status():
    """
    Fetch the current printer state and temperature from OctoPrint
    """
    try:
        # Fetch printer state
        response = requests.get(f"{OCTOPRINT_URL}/printer", headers=HEADERS)
        
        # Check if request was successful
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch data from OctoPrint")
        
        # Parse the response JSON
        data = response.json()
        
        # Extract relevant information
        printer_state = data['state']['text']
        temperatures = data['temperature']
        
        # Return the formatted response
        return PrinterState(state=printer_state, temperature=temperatures)
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint for root to verify if the server is running
@app.get("/")
def root():
    return {"message": "OctoPrint FastAPI Server Running"}

@app.get("/files")
def list_files():
    """
    List all available files on the OctoPrint system
    """
    try:
        response = requests.get(f"{OCTOPRINT_URL}/files", headers=HEADERS)
        if response.status_code != 200:
            raise HTTPException(status_code=response.status_code, detail="Failed to fetch file list from OctoPrint")
        
        data = response.json()
        if 'files' in data:
            return {"files": [file['name'] for file in data['files']]}
        else:
            raise HTTPException(status_code=404, detail="No files found")
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/printer/command")
def send_printer_command(command: str, file_name: str = None):
    """
    Send a command to the printer.
    Available commands: 'start', 'pause', 'resume', 'cancel'.
    
    - 'start': Starts printing the selected file.
    - If no file is selected, it returns an error message.
    """
    commands = {
        "start": "start",
        "pause": "pause",
        "resume": "resume",
        "cancel": "cancel"
    }
    
    if command not in commands:
        raise HTTPException(status_code=400, detail="Invalid command")

    # Send the corresponding command to OctoPrint
    try:
        if command in ['pause', 'resume', 'cancel']:
            # Use OctoPrint job API for pause, resume, and cancel
            response = requests.post(f"{OCTOPRINT_URL}/job", headers=HEADERS, json={"command": commands[command]})
        
        elif command == 'start':
            # Check if a file name is provided for starting the print job
            if not file_name:
                raise HTTPException(status_code=400, detail="No file selected for printing")
            
            # Select the file and then start printing
            select_file_response = requests.post(
                f"{OCTOPRINT_URL}/files/local/{file_name}",
                headers=HEADERS,
                json={"command": "select", "print": True}  # Select and start print
            )
            
            if select_file_response.status_code != 204:
                raise HTTPException(
                    status_code=select_file_response.status_code,
                    detail="Failed to select and start the file for printing"
                )
        
        return {"message": f"Command '{command}' sent successfully"}

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/printer/temperature")
def set_temperature(temperature: TemperatureControl):
    """
    Set the hotend and bed temperature.
    You can set one or both temperatures (hotend and/or bed).
    """
    try:
        # Set hotend (tool) temperature if provided
        if temperature.hotend_temp is not None:
            hotend_payload = {
                "command": "target",
                "targets": {
                    "tool0": temperature.hotend_temp  # tool0 is the first hotend, adjust if you have multiple tools
                }
            }
            hotend_response = requests.post(f"{OCTOPRINT_URL}/printer/tool", headers=HEADERS, json=hotend_payload)
            if hotend_response.status_code != 204:
                raise HTTPException(status_code=hotend_response.status_code, detail="Failed to set hotend temperature")

        # Set bed temperature if provided
        if temperature.bed_temp is not None:
            bed_payload = {
                "command": "target",
                "target": temperature.bed_temp  # 'target' is used for bed temperature
            }
            bed_response = requests.post(f"{OCTOPRINT_URL}/printer/bed", headers=HEADERS, json=bed_payload)
            if bed_response.status_code != 204:
                raise HTTPException(status_code=bed_response.status_code, detail="Failed to set bed temperature")

        return {"message": "Temperature command(s) sent successfully"}

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.post("/printer/move")
def move_printer(movement: MovementControl):
    """
    Move the printer along the X, Y, Z, or E axis.
    You can specify one or more axes and an optional speed (feedrate).
    """
    gcode_command = "G0"  # Default movement command (G0 for non-extrusion moves)

    # Add axis movement commands based on the input
    if movement.x is not None:
        gcode_command += f" X{movement.x}"
    if movement.y is not None:
        gcode_command += f" Y{movement.y}"
    if movement.z is not None:
        gcode_command += f" Z{movement.z}"
    if movement.e is not None:
        gcode_command += f" E{movement.e}"

    # If speed is provided, set the feedrate (F parameter)
    if movement.speed is not None:
        gcode_command += f" F{movement.speed}"

    if len(gcode_command) == 2:  # If no movement was specified, return an error
        raise HTTPException(status_code=400, detail="No movement axis specified")

    # Send the G-code command to OctoPrint
    try:
        response = requests.post(
            f"{OCTOPRINT_URL}/printer/command",
            headers=HEADERS,
            json={"commands": [gcode_command]}
        )

        if response.status_code != 204:
            raise HTTPException(status_code=response.status_code, detail="Failed to move printer")

        return {"message": f"Sent command: {gcode_command}"}

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=str(e))
    


@app.post("/send_sms")
async def send_sms(sms_request: SMSRequest):
    try:
        message = client.messages.create(
            body=sms_request.message,
            from_=twilio_phone_number,
            to=sms_request.to
        )
        return {"message": "SMS sent successfully!", "sid": message.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/send_whatsapp")
async def send_whatsapp(whatsapp_request: WhatsAppMessage):
    try:
        message = client.messages.create(
            body=whatsapp_request.message,
            from_=twilio_whatsapp_number,
            to=f"whatsapp:{whatsapp_request.to}"
        )
        return {"message": "WhatsApp message sent successfully!", "sid": message.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

# Endpoint to handle incoming WhatsApp messages
@app.post("/whatsapp_webhook")
async def whatsapp_webhook(request: Request):
    # Parse the incoming message from Twilio
    form_data = await request.form()
    incoming_msg = form_data.get('Body').lower().strip()
    sender = form_data.get('From')
    
    # Create a Twilio MessagingResponse to send a reply
    response = MessagingResponse()

    # Check the message and respond accordingly
    if 'status' in incoming_msg:
        # Fetch the printer status from the OctoPrint API
        printer_status = get_printer_status()  # Call the existing function
        
        # Construct a reply message with the printer status
        reply = f"Printer Status: {printer_status.state}\nTemperatures: {printer_status.temperature}"
        response.message(reply)

    elif 'files' in incoming_msg:
        # List available files on the OctoPrint system
        files = list_files()  # Call the existing function
        response.message(f"Available Files: {', '.join(files['files'])}")

    else:
        # Default message if unrecognized command
        response.message("Send 'status' to get printer status or 'files' to list available files.")
    
    return str(response)


@app.get("/camera/status")
def get_camera_status():
    """
    Check whether the camera is online or offline.
    Returns 'online' if the camera stream is accessible, 'offline' otherwise.
    """
    try:
        # Attempt to connect to the camera stream
        response = requests.get(OCTOPRINT_WEBCAM_URL, headers=HEADERS, stream=True, timeout=5)  # Set a timeout for the request
        
        # If the response is 200, the camera is online
        if response.status_code == 200:
            logging.info("Camera is online")
            return {"camera_status": "online"}
        else:
            logging.warning(f"Camera returned non-200 status code: {response.status_code}")
            return {"camera_status": "offline", "status_code": response.status_code}
    except requests.exceptions.Timeout:
        logging.error("Connection to the camera stream timed out")
        return {"camera_status": "offline", "error": "Connection timed out"}
    except requests.exceptions.RequestException as e:
        # If there's any connection error, the camera is considered offline
        logging.error(f"Error connecting to the camera stream: {str(e)}")
        return {"camera_status": "offline", "error": str(e)}


@app.get("/camera/stream")
def stream_camera():
    try:
        # Get the camera stream
        response = requests.get(OCTOPRINT_WEBCAM_URL, stream=True)

        if response.status_code != 200:
            raise HTTPException(status_code=503, detail="Camera stream is not available")

        return StreamingResponse(response.raw, media_type="multipart/x-mixed-replace; boundary=frame")

    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Error connecting to the camera stream: {str(e)}")
    

@app.websocket("/ws/camera")
async def websocket_camera(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            # Here, we can fetch and stream the video frames (for MJPEG, or other formats)
            # Replace with your logic to fetch the camera frames
            frame = get_camera_frame()  # Placeholder for getting the actual frame
            await websocket.send_bytes(frame)
            await asyncio.sleep(0.05)  # Control the frame rate (20 FPS here)
    except Exception as e:
        print(f"Connection error: {e}")
    finally:
        await websocket.close()