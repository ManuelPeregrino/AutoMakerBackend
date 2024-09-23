from fastapi import FastAPI, HTTPException
import requests
from pydantic import BaseModel

# Initialize FastAPI app
app = FastAPI()

# OctoPrint API Key and Base URL (replace with your OctoPrint URL)
OCTOPRINT_API_KEY = "9DF6EB616C7E4427B958E45C6E0926F5"
OCTOPRINT_URL = "http://automaker.local/api"

# Headers for the OctoPrint API request
HEADERS = {
    "X-Api-Key": OCTOPRINT_API_KEY
}

# Model for temperature control input
class TemperatureControl(BaseModel):
    hotend_temp: float = None  # Hotend target temperature (optional)
    bed_temp: float = None     # Bed target temperature (optional)

class PrinterState(BaseModel):
    state: str
    temperature: dict

# Model for movement control input
class MovementControl(BaseModel):
    x: float = None  # Distance to move on the X-axis (optional)
    y: float = None  # Distance to move on the Y-axis (optional)
    z: float = None  # Distance to move on the Z-axis (optional)
    e: float = None  # Distance to extrude on the E-axis (optional)
    speed: float = None  # Optional speed for the movement (feedrate)


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