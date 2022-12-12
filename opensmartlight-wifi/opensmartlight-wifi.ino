// #include <EEPROM.h>
#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <ESP8266WebServer.h>
#include <NTPClient.h>
#include <WiFiUdp.h>
#include "./secret.h"

#define tzOffsetInSeconds 3600*8
#define PIN_CONTROL_OUTPUT D2
#define PIN_MOTION_SENSOR D3
#define PIN_LED_MASTER D1
#define PIN_LED_ADJ D4
#define PIN_AMBIENT_PULLUP D7
#define PIN_AMBIENT_INPUT A0

ESP8266WebServer server(80);
int ambient_level;
int onboard_led_level = 0;
bool onboard_led = false;
bool motion_sensor = false;
bool control_output = false;
bool DEBUG = true;
unsigned long tm_last_ambient = 0;
unsigned long tm_last_timesync = 0;
unsigned long tm_last_debugon = millis();


void set_output(bool state, ESP8266WebServer *svr){
  digitalWrite(PIN_CONTROL_OUTPUT, state?1:0);
  control_output = state;
  if(DEBUG) Serial.printf("Output = %s\n", state?"On":"Off");
  if(svr) svr->send(200, "text/html", "");
}

void set_sensor(bool state, ESP8266WebServer *svr){
  digitalWrite(PIN_MOTION_SENSOR, state?1:0);
  motion_sensor = state;
  if(DEBUG) Serial.printf("Sensor = %s\n", state?"On":"Off");
  if(svr) svr->send(200, "text/html", "");
}

void set_onboard_led(bool state, ESP8266WebServer *svr){
  digitalWrite(PIN_LED_MASTER, state?1:0);
  onboard_led = state;
  if(DEBUG) Serial.printf("Onboard LED = %s\n", state?"On":"Off");
  if(svr) svr->send(200, "text/html", "");
}

void set_onboard_led_level(int level, ESP8266WebServer *svr){
  analogWrite(PIN_LED_ADJ, level);
  onboard_led_level = level;
  if(DEBUG) Serial.printf("Onboard LED level = %d\n", level);
  if(svr) svr->send(200, "text/html", "");
}

void set_debug_led(bool state, ESP8266WebServer *svr){
  digitalWrite(LED_BUILTIN_AUX, !state);
  DEBUG = state;
  Serial.printf("DEBUG LED state = %d\n", DEBUG);
  if(state) tm_last_debugon = millis();
  if(svr) svr->send(200, "text/html", "");
}


/* Set these to your desired credentials. */
const char *ssid = WIFI_SSID;                 //Enter your WIFI ssid
const char *password = WIFI_PASSWORD;         //Enter your WIFI password

#if WIFI_STATICIP
// Set your Static IP address
IPAddress local_IP(192, 168, 50, 5);
IPAddress gateway(192, 168, 50, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(8, 8, 8, 8);   //optional
IPAddress secondaryDNS(1, 1, 1, 1); //optional
#endif

// Define NTP Client to get time
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", tzOffsetInSeconds, 7200);
String getTimeString(){
  char buf[16];
  sprintf(buf, "%02d:%02d:%02d", timeClient.getHours(), timeClient.getMinutes(), timeClient.getSeconds());
  return String(buf);
}
String getDateString(){
  time_t epochTime = timeClient.getEpochTime();
  struct tm *ptm = gmtime ((time_t *)&epochTime);
  int monthDay = ptm->tm_mday;
  int currentMonth = ptm->tm_mon+1;
  int currentYear = ptm->tm_year+1900;
  char buf[16];
  sprintf(buf, "%04d-%02d-%02d", currentYear, currentMonth, monthDay);
  return String(buf);
}

void handleRoot() {
  server.send(200, "text/html", R"(<h2>OpenSmartLight</h2>
<p>Date Time: <input type='text' id='datetime' size=24 readonly>&nbsp;<button onclick='update_time()'>Update</button><span id='ntp_reply'></span></p>
<p>Ambient Level: <input type='text' id='ambient' size=16 readonly></p>
<p>Debug LED: <input type='text' id='dbg_led' readonly>&nbsp;
  <button onclick='GET("LED_DEBUG_on")'>On</button>&nbsp;
  <button onclick='GET("LED_DEBUG_off")'>Off</button>&nbsp;
  <button onclick='GET("LED_DEBUG_toggle")'>Toggle</button></p>
<p>Control Output: <input type='text' id='control_output' readonly>&nbsp;
  <button onclick='GET("control_output_on")'>On</button>&nbsp;
  <button onclick='GET("control_output_off")'>Off</button>&nbsp;
  <button onclick='GET("control_output_toggle")'>Toggle</button></p>
<p>Motion Sensor: <input type='text' id='motion_sensor' size=16 readonly>&nbsp;
  <button onclick='GET("motion_sensor_on")'>On</button>&nbsp;
  <button onclick='GET("motion_sensor_off")'>Off</button>&nbsp;
  <button onclick='GET("motion_sensor_toggle")'>Toggle</button></p>
<p>Onboard LED: <input type='text' id='onboard_led' size=16 readonly>&nbsp;
  <button onclick='GET("onboard_led_on")'>On</button>&nbsp;
  <button onclick='GET("onboard_led_off")'>Off</button>&nbsp;
  <button onclick='GET("onboard_led_toggle")'>Toggle</button></p>
<p>Onboard LED Level: <input type='text' id='onboard_led_level' size=16 readonly>&nbsp;
  <span style="background-color:#cccccc; display:inline-flex; align-items: center;">
    <span id='led_level_min'></span>
    <input id='led_level' type="range" min="0" max="200" value="0" onchange='GET("onboard_led_level?brightness="+this.value)'>
    <span id='led_level_max'></span>
  </span></p>
<script>
function getById(id_str){return document.getElementById(id_str);}
function GET(url){
    var xmlHttp = new XMLHttpRequest();
    xmlHttp.open( 'GET', window.location+url, false ); // false for synchronous request
    xmlHttp.send( null );
    return xmlHttp.responseText;
}
function update_time(){
  getById("ntp_reply").innerHTML = GET("update_time");
}
window.onload = () => {
  obj = JSON.parse(GET('status'));
  for(const s of ['datetime', 'dbg_led', 'ambient', 'motion_sensor', 'onboard_led', 'onboard_led_level', 'control_output'])
    getById(s).value = obj[s];
  getById('led_level_min').innerHTML = getById('led_level').min;
  getById('led_level_max').innerHTML = getById('led_level').max;
}
setInterval(window.onload, 1000);
</script>)"
    );
}

void handleStatus(){
  DynamicJsonDocument doc(2048);
  doc["datetime"] = getDateString()+" "+getTimeString();
  doc["dbg_led"] = DEBUG?"ON":"OFF";
  doc["ambient"] = ambient_level;
  doc["motion_sensor"] = motion_sensor?"ON":"OFF";
  doc["onboard_led"] = onboard_led?"ON":"OFF";
  doc["onboard_led_level"] = onboard_led_level;
  doc["control_output"] = control_output?"ON":"OFF";
  String output;
  serializeJson(doc, output);
  server.send(200, "text/html", output);
}

void handleSave() {
  if (server.arg("pass") != "") {
    Serial.println(server.arg("pass"));
  }
}

void initWifi(){
  Serial.print("Connecting to WiFi ...");

#if WIFI_STATICIP
  // Configures static IP address
  if (!WiFi.config(local_IP, gateway, subnet, primaryDNS, secondaryDNS))
    Serial.println("Static IP settings incorrect: failed to configure!");
#endif

  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(2000);
    Serial.print(".");
  }
  Serial.println("\nWiFi connected");
  Serial.println("IP address: ");
  Serial.println(WiFi.localIP());
}

void initServer(){
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/save", handleSave);
  server.on("/update_time", []() {server.send(200, "text/html", timeClient.forceUpdate()?"Success":"Failed");});
  server.on("/LED_DEBUG_on", []() {set_debug_led(true, &server);});
  server.on("/LED_DEBUG_off", []() {set_debug_led(false, &server);});
  server.on("/LED_DEBUG_toggle", []() {set_debug_led(!DEBUG, &server);});
  server.on("/control_output_on", []() {set_output(true, &server);});
  server.on("/control_output_off", []() {set_output(false, &server);});
  server.on("/control_output_toggle", []() {set_output(!control_output, &server);});
  server.on("/motion_sensor_on", []() {set_sensor(true, &server);});
  server.on("/motion_sensor_off", []() {set_sensor(false, &server);});
  server.on("/motion_sensor_toggle", []() {set_sensor(!motion_sensor, &server);});
  server.on("/onboard_led_on", []() {set_onboard_led(true, &server);});
  server.on("/onboard_led_off", []() {set_onboard_led(false, &server);});
  server.on("/onboard_led_toggle", []() {set_onboard_led(!onboard_led, &server);});
  server.on("/onboard_led_level", []() {
    server.hasArg("brightness")?set_onboard_led_level(server.arg("brightness").toInt(), &server):server.send(400, "text/html", "");
    });
  server.begin();
  Serial.println("HTTP server started");
}

int readAmbient(){
  unsigned int sum = 0;
  for(int x=0; x<16; x++)
    sum += analogRead(PIN_AMBIENT_INPUT);
  return sum/16;
}

float parse_output_value(String s){
  char posi = s.lastIndexOf(' ');
  if(posi<0)return 0;
  return s.substring(posi+1).toFloat();
}


void setup() {
  delay(1000);

  pinMode(PIN_CONTROL_OUTPUT, OUTPUT);
  pinMode(PIN_MOTION_SENSOR, OUTPUT);
  pinMode(PIN_LED_MASTER, OUTPUT);
  pinMode(PIN_LED_ADJ, OUTPUT);
  pinMode(PIN_AMBIENT_PULLUP, INPUT_PULLUP);
  pinMode(PIN_AMBIENT_INPUT, INPUT);
  pinMode(LED_BUILTIN_AUX, OUTPUT);

  Serial.begin(115200);
  Serial.println("\nSystem initialized:");
  set_debug_led(true, NULL);
  digitalWrite(LED_BUILTIN, 1);

  initWifi();

  // Update time from Internet
  timeClient.begin();
  timeClient.update();
  Serial.printf("Current datetime = %s %s\n", getDateString(), getTimeString());

  initServer();
  digitalWrite(LED_BUILTIN, 0);
}

void loop() {
  unsigned long tm_curr = millis();

  // Update ambient level
  if(tm_curr-tm_last_ambient>1000){
    ambient_level = readAmbient();
    tm_last_ambient = tm_curr;
  }

  // Synchronize Internet time
  if(tm_curr-tm_last_timesync>3600000*24){
    timeClient.update();
    tm_last_timesync = tm_curr;
  }

  // Auto disable debug
  if(DEBUG && tm_curr-tm_last_debugon>1800000){
    set_debug_led(false, NULL);
  }

  if(Serial.available()){
    String s = Serial.readStringUntil('\n');
    if(DEBUG) Serial.println(s);
  }
 
  server.handleClient();
  delay(1);
}
