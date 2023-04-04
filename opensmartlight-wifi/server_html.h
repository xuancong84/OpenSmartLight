#ifndef SERVER_HTML_H
#define SERVER_HTML_H
char server_html[] = R"aa(<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>OpenSmartLight</title>
<style>
button {
  align-items: center;
  appearance: none;
  background-color: #3EB2FD;
  background-image: linear-gradient(1deg, #4F58FD, #149BF3 99%);
  background-size: calc(100% + 20px) calc(100% + 20px);
  border-radius: 100px;
  border-width: 0;
  box-shadow: none;
  box-sizing: border-box;
  color: #FFFFFF;
  cursor: pointer;
  display: inline-flex;
  font-family: CircularStd,sans-serif;
  font-size: 1rem;
  height: auto;
  justify-content: center;
  line-height: 1;
  padding: 6px 20px;
  position: relative;
  text-align: center;
  text-decoration: none;
  transition: background-color .2s,background-position .2s;
  user-select: none;
  -webkit-user-select: none;
  touch-action: manipulation;
  vertical-align: middle;
  white-space: nowrap;
}
button:active,
button:focus {
  outline: none;
}
button:hover {
  background-position: -20px -20px;
}
button:focus:not(:active) {
  box-shadow: rgba(40, 170, 255, 0.25) 0 0 0 .125em;
}

table, th, td {border: 1px solid;}
input[type=number] {width: 80px;}
input[type=text],input[type=password] {width: 120px;}
h3 {margin-bottom:10px;}
td {padding-left:5px; padding-right:5px;}
input {font-size:15px;}

.bb { font-weight: bold; }
.toggle {
  --width: 80px;
  --height: calc(var(--width) / 3);

  position: relative;
  display: inline-block;
  width: var(--width);
  height: var(--height);
  box-shadow: 0px 1px 3px rgba(0, 0, 0, 0.3);
  border-radius: var(--height);
  cursor: pointer;
  vertical-align: middle;
}
.toggle input {
  display: none;
}
.toggle .slider {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  border-radius: var(--height);
  background-color: #ccc;
  transition: all 0.4s ease-in-out;
}
.toggle input:checked+.slider {
  background-color: #2196F3;
}
.toggle .slider::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: calc(var(--height));
  height: calc(var(--height));
  border-radius: calc(var(--height) / 2);
  background-color: #fff;
  box-shadow: 0px 1px 3px rgba(0, 0, 0, 0.3);
  transition: all 0.4s ease-in-out;
}
.toggle input:checked+.slider::before {
  transform: translateX(calc(var(--width) - var(--height)));
}
.toggle .labels {
  position: absolute;
  top: 4px;
  left: 0;
  width: 100%;
  height: 100%;
  font-size: 16px;
  font-family: sans-serif;
  transition: all 0.4s ease-in-out;
}
.toggle .labels::after {
  content: attr(data-off);
  position: absolute;
  right: 14px;
  color: #4d4d4d;
  opacity: 1;
  text-shadow: 1px 1px 2px rgba(0, 0, 0, 0.4);
  transition: all 0.4s ease-in-out;
}
.toggle .labels::before {
  content: attr(data-on);
  position: absolute;
  left: 18px;
  color: #ffffff;
  opacity: 0;
  text-shadow: 1px 1px 2px rgba(255, 255, 255, 0.4);
  transition: all 0.4s ease-in-out;
}
.toggle input:checked~.labels::after {
  opacity: 0;
}
.toggle input:checked~.labels::before {
  opacity: 1;
}
</style>
</head>
<body>
<div style="height: 100%; width: calc(24% - 12px); resize: horizontal; overflow: auto; border: 2px; position:absolute; left:10px">
  <h2>OpenSmart Nodes:</h2>
  <select id="node_list" size=20 style="width:100%;"></select>
  </div>
<div style="height:100%; width:calc(75% - 4px); overflow:auto; position:absolute; border: 2px; right:0">
<h2>OpenSmartLight (Open-source Smart Light Controller) &nbsp;
  Updating: <label class="toggle"><input id='isActive' type="checkbox" onchange='isActive=this.checked' checked>
  <span class="slider"></span><span class="labels" data-on="ON" data-off="OFF"></span></label>
  <span id='svr_reply' style='color:red'></span></h2>
<p>Date Time: <input type='text' id='datetime' size=32 style="width:auto" readonly>&nbsp;
  Timezone: <input type='number' id='timezone' onchange='set_value(this)'>&nbsp;
  <button onclick='GET2("update_time")'>Synchronize Time</button>&nbsp;
  <button onclick='update_status("static", true)'>Reload Parameters</button>
  </p>
<p>Board Info: <input type='text' id='board_info' size=100 style="width:auto" readonly></p>
<p><table><tr>
<td>Debug LED: <label class="toggle"><input id='dbg_led' type="checkbox" onchange='set_ckbox(this)'>
  <span class="slider"></span><span class="labels" data-on="ON" data-off="OFF"></span></label></td>
<td>Control Output: <label class="toggle"><input id='control_output' type="checkbox" onchange='set_ckbox(this)'>
  <span class="slider"></span><span class="labels" data-on="ON" data-off="OFF"></span></label></td>
<td>System LED: <label class="toggle"><input id='sys_led' type="checkbox" onchange='set_ckbox(this)'>
  <span class="slider"></span><span class="labels" data-on="ON" data-off="OFF"></span></label>
  <span style="display:inline-flex; vertical-align: middle;">
    <input type="range" min="0" max="255" value="0" style="width:200px" oninput='GET2("sys_led_level?level="+this.value)'>
  </span></td>
</tr></table></p>
<hr>
<h3>Ambient Light Threshold Adjustment &nbsp;&nbsp; Current Level: <input type='text' id='ambient' readonly></h3>
<table><tbody>
  <tr><td>DARK_TH_LOW</td><td> <input type='number' id='DARK_TH_LOW' onchange='set_value(this)'> </td><td> The darkness level below which it enters day mode. </td></tr>
  <tr><td>DARK_TH_HIGH</td><td> <input type='number' id='DARK_TH_HIGH' onchange='set_value(this)'> </td><td> The darkness level above which it enters night mode. </td></tr>
</tbody></table>
<hr>
<h3>Onboard LED Adjustment &nbsp;&nbsp; Status: <label class="toggle"><input id='onboard_led' type="checkbox" onchange='set_ckbox(this)'>
  <span class="slider"></span><span class="labels" data-on="ON" data-off="OFF"></span></label></h3>
<p>Onboard LED Level: <input type='number' id='onboard_led_level' onchange='GET2("onboard_led_level?level="+this.value)'>&nbsp;
  <span style="background-color:#dddddd; display:inline-flex; align-items: center;">
    <span id='led_level_min'></span>
    <input id='led_level' type="range" min="0" max="200" value="0" style="width:400px" onchange='GET2("onboard_led_level?level="+this.value)'>
    <span id='led_level_max'></span>
  </span></p>
<table>
  <tr><td>LED_BEGIN </td><td> <input type='number' id='LED_BEGIN' onchange='set_value(this)'> </td><td> The initial LED level when lighting up (or the final LED level when shutting down). </td></tr>
  <tr><td>LED_END </td><td> <input type='number' id='LED_END' onchange='set_value(this)'> </td><td> The final LED level when lighting up (or the initial LED level when shutting down). </td></tr>
  <tr><td>GLIDE_TIME </td><td> <input type='number' id='GLIDE_TIME' onchange='set_value(this)'> </td><td> The duration (in milliseconds) of turning on the LED gradually.
  <button id='glide_led' onclick='GET2("glide_led_"+(getById("onboard_led").checked?"off":"on"))'>Glide LED ON</button></td></tr>
<table>
<hr>
<p><h3>Mid-night Start/Stop Times &nbsp;&nbsp;&nbsp; Is now mid-night? <input type='text' id='is_midnight' readonly></h3>
<table>
  <tr><th>Day of Week</th><th>Monday</th><th>Tuesday</th><th>Wednesday</th><th>Thursday</th><th>Friday</th><th>Saturday</th><th>Sunday</th><th><b>Everyday</b></th></tr>
  <tr><td>Start Time</td>
    <td><input type="time" id="midnight_start0" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_start1" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_start2" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_start3" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_start4" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_start5" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_start6" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_start" onchange='changeALL(this)' onblur='set_times(this)'></td></tr>
  <tr><td>End Time</td>
    <td><input type="time" id="midnight_stop0" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_stop1" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_stop2" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_stop3" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_stop4" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_stop5" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_stop6" onblur='set_value(this)'></td>
    <td><input type="time" id="midnight_stop"  onchange='changeALL(this)' onblur='set_times(this)'></td></tr>
</table>
<hr>
<h3>Motion Sensor &nbsp;&nbsp; Status: <label class="toggle"><input id='motion_sensor' type="checkbox" onchange='set_ckbox(this)'>
  <span class="slider"></span><span class="labels" data-on="ON" data-off="OFF"></span></label> &nbsp;&nbsp;
  <button onclick='show_list()' class='bb'>View History</button></h3>
<table>
<tr><td>MOV_TRIG_TH</td> <td><input type='number' id='MOV_TRIG_TH' onchange='set_value(this)'></td> <td>The MOV threshold level to trigger light-on. </td>
  <td rowspan=6>Motion Sensor Log:<br><textarea id='sensor_output' rows=10 cols=20 style='resize:both;' readonly></textarea></td></tr>
<tr><td>MOV_CONT_TH</td> <td><input type='number' id='MOV_CONT_TH' onchange='set_value(this)'></td> <td>The MOV threshold level to maintain light-on. </td></tr>
<tr><td>OCC_TRIG_TH</td> <td><input type='number' id='OCC_TRIG_TH' onchange='set_value(this)'></td> <td>The OCC threshold level to trigger light-on. </td></tr>
<tr><td>OCC_CONT_TH</td> <td><input type='number' id='OCC_CONT_TH' onchange='set_value(this)'></td> <td>The OCC threshold level to maintain light-on. </td></tr>
<tr><td>DELAY_ON_MOV</td> <td><input type='number' id='DELAY_ON_MOV' onchange='set_value(this)'></td> <td>The duration to extend light-on time upon MOV. </td></tr>
<tr><td>DELAY_ON_OCC</td> <td><input type='number' id='DELAY_ON_OCC' onchange='set_value(this)'></td> <td>The duration to extend light-on time upon OCC. </td></tr>
</table>
<hr>
<h3>WIFI Settings &nbsp;&nbsp;SSID: <input id='wifi_ssid' type='text' onblur='set_value(this)'> &nbsp; Password: <input id='wifi_password' type='password' onblur='set_value(this)'>
  &nbsp; <button onclick='GET2("restart_wifi")' class='bb'>Restart WIFI</button></h3>
<table>
<tr><th>IP Address</th><th>Gateway</th><th>Subnet</th><th>DNS primary</th><th>DNS secondary</th></tr>
<tr>
  <td><input onblur='set_value(this)' type="text" minlength="7" maxlength="15" size="15" pattern="^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$" id='wifi_IP'></td>
  <td><input onblur='set_value(this)' type="text" minlength="7" maxlength="15" size="15" pattern="^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$" id='wifi_gateway'></td>
  <td><input onblur='set_value(this)' type="text" minlength="7" maxlength="15" size="15" pattern="^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$" id='wifi_subnet'></td>
  <td><input onblur='set_value(this)' type="text" minlength="7" maxlength="15" size="15" pattern="^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$" id='wifi_DNS1'></td>
  <td><input onblur='set_value(this)' type="text" minlength="7" maxlength="15" size="15" pattern="^((\d{1,2}|1\d\d|2[0-4]\d|25[0-5])\.){3}(\d{1,2}|1\d\d|2[0-4]\d|25[0-5])$" id='wifi_DNS2'></td>
</tr>
</table>
<p><button onclick="location.href='/update'" class='bb'>OTA Firmware Update</button>&nbsp;
  <button onclick='alert(GET1("save_config"))' title='Save config file to persist across restarts' class='bb'>Save Settings</button>&nbsp;
  <button onclick='alert(GET1("load_config"));update_status("static", true)' title='Load settings from config file' class='bb'>Load Settings</button>&nbsp;
  <button onclick='GET2("reboot")' class='bb'>Reboot</button></p>
<div id="popup" style="display:block; visibility:hidden; position: absolute; z-index: 9; background-color: #f1f1f1; border: 1px solid #d3d3d3; text-align: center;">
  <div id="popup_header" style="padding: 10px; cursor: move; z-index: 10; background-color: #219633; color: #fff;">
    <b>Log History</b>&nbsp;
    <button style="background:#c00" onclick='show_list(GET1("log_history?delete="+current_logfile))'>Delete Current</button>&nbsp;
    <button style="background:#c00" onclick='show_list(GET1("log_history?delete=ALL"))'>Delete ALL</button>
    <a style="cursor:pointer; color:red; float:right; font-size:xx-large; margin-top:-4px" onclick='hide_details()'>☒</a>
  </div>
  <div style="width:800px; height:600px; display:flex; resize:both; overflow:auto">
    <div style="height: 100%; width: 25%;"><select id="popup_list" size=10 style="width:100%; height:100%;"></select></div>&nbsp;
    <div style="height: 100%; width: 75%"><textarea id="popup_log" style="width:100%; height:100%; box-sizing:border-box" readonly></textarea></div>
  </div>
</div>
</div>

<script>
var this_ip = null;
var isActive = true;
var countDown = 0;
var svr_reply = getById('svr_reply');
var current_logfile = "";
var xmlHttp = new XMLHttpRequest();
function getById(id_str){return document.getElementById(id_str);}
function GET1(url){
  xmlHttp.open('GET', "/"+url, false);
  xmlHttp.send(null);
  return xmlHttp.responseText;
}
function GET2(url, cb=null){
  xmlHttp.open('GET', "/"+url);
  if(cb!=null) xmlHttp.onload = cb;
  xmlHttp.send(null);
  return xmlHttp.responseText;
}
function GET(url){
  while(true){
    try{ return GET1(url); }catch(err){
      isActive = false;
      getById('isActive').checked = false;
    }
  }
}
function changeALL(obj){
  for(var x=0; x<7; x++)
    getById(obj.id+x).value = obj.value;
}
function set_value2(id, value){
  svr_reply.innerHTML = GET('set_value?'+id+'='+value);
  countDown = 4;
}
function set_value(obj){ set_value2(obj.id, obj.value); }
function set_ckbox(obj){
  GET(obj.id+'_'+(obj.checked?'on':'off'));
}
function set_times(obj){
  var ret = "set_times?"+obj.id+"=";
  for(var x=0; x<7; ++x)
    ret += getById(obj.id+x).value+' ';
  svr_reply.innerHTML = GET(ret);
  countDown = 4;
}
function goto(e){
  if(e.value==this_ip){
    var new_name = prompt('Please enter the new name for this device:');
    if(new_name!=null) set_value2('node_name', new_name);
  }else window.location.href = "http://"+e.value;
}
var statusRC = 0;
function update_status(cmd='status', force=false){
  if(--countDown>0) svr_reply.innerText += '.';
  else svr_reply.innerText = "";

  if(!isActive && !force) return;
  if(statusRC>0) return;
  statusRC++;
  GET2(cmd, (e)=>{
    statusRC--;
    try{obj = JSON.parse(e.target.responseText)} catch(e){return}
    for(const s in obj){
      var elem = getById(s);
      if(elem==null) continue;
      if(elem.type=='checkbox')elem.checked=obj[s];
      else if(elem.type=='select-one'){
      	elem.innerHTML = '';
      	var node_list = obj[s];
      	for(var ip in node_list)
      	  elem.innerHTML += '<option value="'+ip+'" style="font-size:24px" onclick="goto(this)">'+node_list[ip]+' ('+ip+')</option>';
      }else elem.value = obj[s];
    }
    if('onboard_led_level' in obj) getById('led_level').value = obj['onboard_led_level'];
    if('onboard_led' in obj) getById('glide_led').innerHTML = "Glide LED "+(obj['onboard_led']?'OFF':'ON');
    if('svr_reply' in obj){svr_reply.innerText=svr_reply.value; countDown = 4;}
    if('this_ip' in obj){
      this_ip = obj['this_ip'];
      for(var e of getById('node_list').children)
        if(e.value==this_ip) e.selected='selected';
    }
  });
}
var popup = getById("popup");
function hide_details(){ popup.style.visibility = "hidden" }
function dragElement(elmnt) {
  var pos1 = 0, pos2 = 0, pos3 = 0, pos4 = 0;
  getById('popup_header').onmousedown = dragMouseDown;

  function dragMouseDown(e) {
    e = e || window.event;
    e.preventDefault();
    // get the mouse cursor position at startup:
    pos3 = e.clientX;
    pos4 = e.clientY;
    document.onmouseup = closeDragElement;
    document.onmousemove = elementDrag;
  }

  function elementDrag(e) {
    e = e || window.event;
    e.preventDefault();
    pos1 = pos3 - e.clientX;
    pos2 = pos4 - e.clientY;
    pos3 = e.clientX;
    pos4 = e.clientY;
    elmnt.style.top = (elmnt.offsetTop - pos2) + "px";
    elmnt.style.left = (elmnt.offsetLeft - pos1) + "px";
  }

  function closeDragElement() {
    document.onmouseup = null;
    document.onmousemove = null;
  }
}
function show_log(fn){
  getById('popup_log').value = GET1('logs/'+fn);
  current_logfile = fn;
}
function show_list(filelist=0){
  try{
    filelist = filelist==0?GET1("log_history"):filelist;
    if(popup.style.visibility!="visible"){
      popup.style.visibility = "visible";
      popup.style.top = (document.scrollingElement.scrollTop+50)+"px";
    }
    var popup_list = getById('popup_list');
    popup_list.innerHTML = "";
    for(var fn of filelist.split(' ')) if(fn)
      popup_list.innerHTML += "<option onclick='show_log(\"" + fn + "\");'>"+fn+"</option>";
    if(filelist) show_log(filelist.split(' ')[0]);
  }catch(err){alert('Failed to get sensor history!');}
}
window.onload = () => {
  getById('led_level_min').innerHTML = getById('led_level').min;
  getById('led_level_max').innerHTML = getById('led_level').max;
  update_status('static');
}
dragElement(popup);
setInterval(update_status, 1000);
</script>
</body></html>
)aa";

#endif
