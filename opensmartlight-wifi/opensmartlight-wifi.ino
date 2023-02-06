#include <Esp.h>
#include <EEPROM.h>
#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <ESPAsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <AsyncElegantOTA.h>
#include <NTPClient.h>
#include <DNSServer.h>
#include <WiFiUdp.h>
#include <md5.h>
#include "./secret.h"
#include "./server_html.h"

#define tzOffsetInSeconds 3600*8
#define PIN_CONTROL_OUTPUT D2
#define PIN_MOTION_SENSOR D3
#define PIN_LED_MASTER D1
#define PIN_LED_ADJ D5
#define PIN_AMBIENT_PULLUP D7
#define PIN_AMBIENT_INPUT A0
#define SENSOR_LOG_MAX  120

// Saved parameters
unsigned int DARK_TH_LOW = 950;
unsigned int DARK_TH_HIGH = 990;
unsigned int DELAY_ON_MOV = 30000;
unsigned int DELAY_ON_OCC = 20000;
unsigned int OCC_TRIG_TH = 65530;
unsigned int OCC_CONT_TH = 600;
unsigned int MOV_TRIG_TH = 400;
unsigned int MOV_CONT_TH = 250;
unsigned int LED_BEGIN = 100;
unsigned int LED_END = 125;
unsigned int GLIDE_TIME = 800;

AsyncWebServer server(80);
DNSServer *dnsServer = NULL;
const byte DNS_PORT = 53; 
int ambient_level;
int onboard_led_level = 0;
bool is_dark_mode = false;
bool is_smartlight_on = false;
bool onboard_led = false;
bool motion_sensor = false;
bool control_output = false;
bool DEBUG = false;
bool SYSLED = false;
String sensor_log;
String midnight_starts[7] = { "23:00", "23:00", "23:00", "23:00", "00:00", "00:00", "23:00" };
String midnight_stops[7] = { "07:00", "07:00", "07:00", "07:00", "07:00", "07:00", "07:00" };

bool reboot = false;
unsigned long tm_last_ambient = 0;
unsigned long tm_last_timesync = 0;
unsigned long tm_last_debugon = millis();

// Saveable parameters
#define N_params 11
String g_params[N_params] = {"DARK_TH_LOW", "DARK_TH_HIGH", "DELAY_ON_MOV", "DELAY_ON_OCC", "OCC_TRIG_TH", "OCC_CONT_TH", "MOV_TRIG_TH", "MOV_CONT_TH", "LED_BEGIN", "LED_END", "GLIDE_TIME"};
unsigned int *g_pointer[N_params] = {&DARK_TH_LOW, &DARK_TH_HIGH, &DELAY_ON_MOV, &DELAY_ON_OCC, &OCC_TRIG_TH, &OCC_CONT_TH, &MOV_TRIG_TH, &MOV_CONT_TH, &LED_BEGIN, &LED_END, &GLIDE_TIME};
bool set_value(String varname, unsigned int value){
  for(int x=0; x<N_params; x++)
    if(varname==g_params[x]){
      *g_pointer[x] = value;
      return true;
    }
  return false;
}

String md5(char *buf, int len) {
  char out[20];
  md5_context_t ctx;
  MD5Init(&ctx);
  MD5Update(&ctx, (const uint8_t*)buf, len);
  MD5Final((uint8_t*)out, &ctx);
  return String(out);
}

int calc_checksum(char *buf, int len){
  return 0;
}

void save_to_EEPROM(){
  String midnight_str="";
  for(int x=0; x<7; x++)
    midnight_str += (midnight_starts[x]+" "+midnight_stops[x]);

  char buf[sizeof(int)*N_params+midnight_str.length()+1+8];
  int posi = 0;
  for(int x=0; x<N_params; x++){
    *(unsigned int*)(&buf[posi]) = *g_pointer[x];
    posi += sizeof(unsigned int);
  }
  strcpy(&buf[posi], midnight_str.c_str());
  posi += midnight_str.length()+1;
}

bool load_EEPROM(){
  return true;
}

/* Set these to your desired credentials. */
#if defined(WIFI_SSID) && defined(WIFI_PASSWORD)
const char *ssid = WIFI_SSID;                 //Enter your WIFI ssid
const char *password = WIFI_PASSWORD;         //Enter your WIFI password
#define WIFI_STATICIP
#else
const char *ssid = "";                 //Enter your WIFI ssid
const char *password = "";         //Enter your WIFI password
#endif

#ifdef WIFI_STATICIP
// Set your Static IP address
IPAddress local_IP(192, 168, 50, 5);
IPAddress gateway(192, 168, 50, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(8, 8, 8, 8);   //optional
IPAddress secondaryDNS(1, 1, 1, 1); //optional
#endif

void set_output(bool state){
  digitalWrite(PIN_CONTROL_OUTPUT, state?1:0);
  control_output = state;
  if(DEBUG) Serial.printf("Output = %s\n", state?"On":"Off");
}

void set_sensor(bool state){
  digitalWrite(PIN_MOTION_SENSOR, state?1:0);
  motion_sensor = state;
  if(DEBUG) Serial.printf("Sensor = %s\n", state?"On":"Off");
}

void set_onboard_led(bool state){
  digitalWrite(PIN_LED_MASTER, state?1:0);
  onboard_led = state;
  if(DEBUG) Serial.printf("Onboard LED = %s\n", state?"On":"Off");
}

void glide_onboard_led(bool state){
  int level;
  float spd = ((float)GLIDE_TIME)/((LED_BEGIN+LED_END+1)*(abs(int(LED_END-LED_BEGIN))+1)/2);
  if(state){  // turn on gradually
    analogWrite(PIN_LED_ADJ, LED_BEGIN);
    digitalWrite(PIN_LED_MASTER, 1);
    for(level=LED_BEGIN; level<=LED_END; level++){
      delay((unsigned long)(level*spd));
      analogWrite(PIN_LED_ADJ, level);
    }
  }else{  // turn off gradually
    analogWrite(PIN_LED_ADJ, LED_END);
    for(level=LED_END; level>=LED_BEGIN; level--){
      delay((unsigned long)(level*spd));
      analogWrite(PIN_LED_ADJ, level);
    }
    digitalWrite(PIN_LED_MASTER, 0);
    analogWrite(PIN_LED_ADJ, 0);
  }
  onboard_led = state;
  onboard_led_level = level;

  if(DEBUG) Serial.printf("Onboard LED gradually turned %s to %d\n", state?"ON":"OFF", level);
}

void set_onboard_led_level(int level){
  analogWrite(PIN_LED_ADJ, level);
  onboard_led_level = level;
  if(DEBUG) Serial.printf("Onboard LED level = %d\n", level);
}

void set_debug_led(bool state){
  digitalWrite(LED_BUILTIN_AUX, !state);
  DEBUG = state;
  Serial.printf("DEBUG LED state = %d\n", DEBUG);
  if(state) tm_last_debugon = millis();
}

void set_system_led(bool state){
  digitalWrite(LED_BUILTIN, !state);
  SYSLED = state;
  if(DEBUG) Serial.printf("System LED state = %d\n", SYSLED);
}

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
String weekDays[7]={"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"};
String getWeekdayString(){
  return weekDays[timeClient.getDay()];
}

boolean isIp(String str) {
  for (size_t i = 0; i < str.length(); i++) {
    int c = str.charAt(i);
    if (c != '.' && (c < '0' || c > '9'))
      return false;
  }
  return true;
}

void smartlight_off(){
  if(control_output) set_output(false);
  if(onboard_led) glide_onboard_led(false);
  is_smartlight_on = false;
}

bool is_midnight(){
  int weekday = (timeClient.getDay()+6)%7;
  String midnight_start = midnight_starts[weekday], midnight_stop = midnight_stops[weekday];
  int hours = timeClient.getHours(), minutes = timeClient.getMinutes();
  String midnight_time = getTimeString().substring(0, 5);
  if(midnight_start.isEmpty() || midnight_stop.isEmpty()) return false;
  if(midnight_stop > midnight_start) // midnight starts after 0am
    return midnight_time>=midnight_start && midnight_time<=midnight_stop;
  return midnight_time>=midnight_start || midnight_time<=midnight_stop;
}

void smartlight_on(){
  is_midnight() ? glide_onboard_led(true) : set_output(true);
  is_smartlight_on = true;
}

void handleRoot(AsyncWebServerRequest *request) {
  if(dnsServer && !isIp(request->host())){
    AsyncWebServerResponse *response = request->beginResponse(302, "text/plain", "");
    response->addHeader("Location", "http://" + request->client()->localIP().toString());
    request->send(response);
    request->client()->stop();
    return;
  }
  request->send_P(200, "text/html", server_html);
}

void handleStatus(AsyncWebServerRequest *request){
  DynamicJsonDocument doc(2048);
  doc["datetime"] = getDateString()+" ("+getWeekdayString()+") "+getTimeString();
  doc["dbg_led"] = DEBUG;
  doc["sys_led"] = SYSLED;
  doc["ambient"] = ambient_level;
  doc["motion_sensor"] = motion_sensor;
  doc["onboard_led"] = onboard_led;
  doc["onboard_led_level"] = onboard_led_level;
  doc["control_output"] = control_output;
  doc["sensor_output"] = sensor_log;
  doc["is_midnight"] = is_midnight();
  String output;
  serializeJson(doc, output);
  request->send(200, "text/html", output);
}

void handleStatic(AsyncWebServerRequest *request){
  DynamicJsonDocument doc(2048);
  for(int x=0; x<N_params; x++)
    doc[g_params[x]] = *g_pointer[x];
  for(int x=0; x<7; x++){
    doc["midnight_start"+String(x)] = midnight_starts[x];
    doc["midnight_stop"+String(x)] = midnight_stops[x];
  }
  String output;
  serializeJson(doc, output);
  request->send(200, "text/html", output);
}

void initWifi(){
  Serial.print("Connecting to WiFi ...");

#ifdef WIFI_STATICIP
  // Configures static IP address
  if (!WiFi.config(local_IP, gateway, subnet, primaryDNS, secondaryDNS))
    Serial.println("Static IP settings incorrect: failed to configure!");
#endif

  WiFi.begin(ssid, password);
  for(int x=0; x<=60; ++x){
    if(WiFi.status() == WL_CONNECTED) break;
    delay(1000);
    Serial.print(".");
  }
  if(WiFi.status() == WL_CONNECTED){
    Serial.println("\nWiFi connected");
    Serial.println("IP address: ");
    Serial.println(WiFi.localIP());
  }else{
    Serial.println("\nUnable to connect to WiFi, creating hotspot 'OpenSmartLight' ...");
    WiFi.softAP("OpenSmartLight");
    IPAddress apIP = WiFi.softAPIP();
    Serial.print("Hotspot IP address: ");
    Serial.println(apIP);
    dnsServer = new DNSServer();
    dnsServer->setErrorReplyCode(DNSReplyCode::NoError);
    dnsServer->start(DNS_PORT, "*", apIP);
  }
}

void initServer(){
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/static", handleStatic);
  server.on("/reboot", [](AsyncWebServerRequest *request) {reboot = true; request->send(200, "text/html", "");});
  server.on("/update_time", [](AsyncWebServerRequest *request) {tm_last_timesync=0; request->send(200, "text/html", "");});
  server.on("/dbg_led_on", [](AsyncWebServerRequest *request) {set_debug_led(true);request->send(200, "text/html", "");});
  server.on("/dbg_led_off", [](AsyncWebServerRequest *request) {set_debug_led(false);request->send(200, "text/html", "");});
  server.on("/sys_led_on", [](AsyncWebServerRequest *request) {set_system_led(true);request->send(200, "text/html", "");});
  server.on("/sys_led_off", [](AsyncWebServerRequest *request) {set_system_led(false);request->send(200, "text/html", "");});
  server.on("/control_output_on", [](AsyncWebServerRequest *request) {set_output(true);request->send(200, "text/html", "");});
  server.on("/control_output_off", [](AsyncWebServerRequest *request) {set_output(false);request->send(200, "text/html", "");});
  server.on("/motion_sensor_on", [](AsyncWebServerRequest *request) {set_sensor(true);request->send(200, "text/html", "");});
  server.on("/motion_sensor_off", [](AsyncWebServerRequest *request) {set_sensor(false);request->send(200, "text/html", "");});
  server.on("/glide_led_on", [](AsyncWebServerRequest *request) {glide_onboard_led(true);request->send(200, "text/html", "");});
  server.on("/glide_led_off", [](AsyncWebServerRequest *request) {glide_onboard_led(false);request->send(200, "text/html", "");});  
  server.on("/onboard_led_on", [](AsyncWebServerRequest *request) {set_onboard_led(true);request->send(200, "text/html", "");});
  server.on("/onboard_led_off", [](AsyncWebServerRequest *request) {set_onboard_led(false);request->send(200, "text/html", "");});
  server.on("/onboard_led_level", [](AsyncWebServerRequest *request) {
    if(request->hasArg("brightness")){
      set_onboard_led_level(request->arg("brightness").toInt());
      request->send(200, "text/html", "");
    }else
      request->send(400, "text/html", "");
    });
  server.on("/set_value", [](AsyncWebServerRequest *request) {
    String varname = request->argName(0);
    unsigned int value = request->arg((size_t)0).toInt();
    request->send(set_value(varname, value)?200:400, "text/html", "");
    });
  server.on("/set_midnight_times", [](AsyncWebServerRequest *request){
    if(request->hasArg("midnight_times")){
      String s = request->arg("midnight_times");
      for(int x=0; x<7; x++){
        int posi = s.indexOf(' ');
        midnight_starts[x] = (posi>=0?s.substring(0, posi):s);
        s = s.substring(posi+1);
        posi = s.indexOf(' ');
        midnight_stops[x] = (posi>=0?s.substring(0, posi):s);
        s = s.substring(posi+1);
      }
      request->send(200, "text/html", "");
    }else
      request->send(400, "text/html", "");
  });
  server.onNotFound([](AsyncWebServerRequest *request){request->send(404, "text/plain", "Content not found.");});
  AsyncElegantOTA.begin(&server);
  server.begin();
  Serial.println("HTTP server started");
}

int readAmbient(){
  unsigned int sum = 0;
  for(int x=0; x<8; x++)
    sum += analogRead(PIN_AMBIENT_INPUT);
  return sum/8;
}

float parse_output_value(String s){
  char posi = s.lastIndexOf(' ');
  if(posi<0)return 0;
  return s.substring(posi+1).toFloat();
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(LED_BUILTIN_AUX, OUTPUT);
  pinMode(PIN_CONTROL_OUTPUT, OUTPUT);
  pinMode(PIN_MOTION_SENSOR, OUTPUT);
  pinMode(PIN_LED_MASTER, OUTPUT);
  pinMode(PIN_LED_ADJ, OUTPUT);
  pinMode(PIN_AMBIENT_PULLUP, INPUT_PULLUP);
  pinMode(PIN_AMBIENT_INPUT, INPUT);

  digitalWrite(LED_BUILTIN, 0);
  digitalWrite(LED_BUILTIN_AUX, 0);

  Serial.begin(115200);
  Serial.setTimeout(100L);
  Serial.println("\nSystem initialized:");

  initWifi();
  digitalWrite(LED_BUILTIN, 1);

  // Update time from Internet
  timeClient.begin();
  timeClient.update();
  Serial.printf("Current datetime = %s %s\n", getDateString(), getTimeString());

  initServer();
  digitalWrite(LED_BUILTIN_AUX, 1);
}

unsigned long elapse = millis();
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

  // Handle reboot
  if(reboot){
    delay(200);
    ESP.restart();
  }

  // Auto disable debug
  if(DEBUG && tm_curr-tm_last_debugon>1800000){
    set_debug_led(false);
  }

  // Receive data from motion sensor
  int s_mask = 0;
  while(Serial.available()){
    String s = Serial.readStringUntil('\n');
    s.trim();
    if(s.isEmpty()) break;
    while(sensor_log.length()+s.length()>SENSOR_LOG_MAX){
      int posi = sensor_log.indexOf('\n');
      if(posi<0) sensor_log.clear();
      else sensor_log.remove(0, posi+1);
    }
    sensor_log.concat(s+"\n");
    if(s.startsWith("mov") && parse_output_value(s)>=MOV_CONT_TH) s_mask |= 1;
    if(s.startsWith("occ") && parse_output_value(s)>=OCC_CONT_TH) s_mask |= 2;
    if((s.startsWith("mov") && parse_output_value(s)>=MOV_TRIG_TH) || (s.startsWith("occ") && parse_output_value(s)>=OCC_TRIG_TH)) s_mask |= 4;
    if(DEBUG) Serial.println(s);
  }

  // Hotspot captive portal
  if(dnsServer)
    dnsServer->processNextRequest();

  // Main logic loop
  if(is_dark_mode){ // in night
    if(is_smartlight_on){ // when light/led is on
      unsigned long ul = 0;
      if(s_mask & 1){
        ul = millis()+DELAY_ON_MOV;
        if(ul>elapse) elapse = ul;
      }
      if(s_mask & 2){
        ul = millis()+DELAY_ON_OCC;
        if(ul>elapse) elapse = ul;
      }
      if(millis()>elapse){
        smartlight_off();
        delay(500); // wait for light sensor to stablize
      }
    }else{  // when light/led is off
      if(s_mask & 4){
        smartlight_on();
        elapse = millis()+DELAY_ON_MOV;
      }else if(ambient_level<DARK_TH_LOW){ // return to day mode
        set_sensor(false);
        is_dark_mode = false;
      }
    }
  }else{ // in day
    if(ambient_level>DARK_TH_HIGH){
      set_sensor(true);
      is_dark_mode = true;
    }
  }
 
  delay(1);
}
