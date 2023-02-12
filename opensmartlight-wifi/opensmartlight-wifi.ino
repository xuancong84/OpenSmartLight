#include <Esp.h>
#include <LittleFS.h>
#include <ArduinoJson.h>
#include <IPAddress.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <ESPAsyncTCP.h>
#include <ESPAsyncWebServer.h>
#include <AsyncElegantOTA.h>
#include <NTPClient.h>
#include <DNSServer.h>
#include <WiFiUdp.h>
#include <unistd.h>
#include <md5.h>
#include <stdio.h>
#include "./secret.h" // put your WIFI credentials in this file, or comment this line out
#include "./server_html.h"

#define PIN_CONTROL_OUTPUT D2
#define PIN_MOTION_SENSOR D3
#define PIN_LED_MASTER D1
#define PIN_LED_ADJ D5
#define PIN_AMBIENT_PULLUP D7
#define PIN_AMBIENT_INPUT A0
#define SENSOR_LOG_MAX  120
#define LOGFILE_MAX_SIZE  200000
#define LOGFILE_MAX_NUM  8
#define WIFI_NAME "OpenSmartLight"

void blink_halt(){
  while(1){
    digitalWrite(LED_BUILTIN, 1);
    delay(1000);
    digitalWrite(LED_BUILTIN, 0);
    delay(1000);
  }
}

ADC_MODE(ADC_VCC);

// Saved parameters
float timezone = 8;
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

// WIFI parameters
#ifndef WIFI_SSID
#define WIFI_SSID ""
#endif

#ifndef WIFI_PASSWORD
#define WIFI_PASSWORD ""
#endif

#ifndef WIFI_IP
#define WIFI_IP IPAddress()
#endif

#ifndef WIFI_GATEWAY
#define WIFI_GATEWAY IPAddress()
#endif

#ifndef WIFI_SUBNET
#define WIFI_SUBNET IPAddress()
#endif

#ifndef WIFI_DNS1
#define WIFI_DNS1 IPAddress()
#endif

#ifndef WIFI_DNS2
#define WIFI_DNS2 IPAddress()
#endif


String wifi_ssid = WIFI_SSID;             //Enter your WIFI ssid
String wifi_password = WIFI_PASSWORD;     //Enter your WIFI password
IPAddress wifi_IP = WIFI_IP;
IPAddress wifi_gateway = WIFI_GATEWAY;
IPAddress wifi_subnet = WIFI_SUBNET;
IPAddress wifi_DNS1 = WIFI_DNS1;          //optional
IPAddress wifi_DNS2 = WIFI_DNS2;          //optional

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
bool DEBUG = true;
bool SYSLED = false;
String sensor_log, svr_reply;
String midnight_starts[7] = { "23:00", "23:00", "23:00", "23:00", "00:00", "00:00", "23:00" };
String midnight_stops[7] = { "07:00", "07:00", "07:00", "07:00", "07:00", "07:00", "07:00" };

File fp_hist;
int do_glide = 0;
bool reboot = false, restart_wifi = false, update_ntp = false;
unsigned long tm_last_ambient = 0;
unsigned long tm_last_timesync = 0;
unsigned long tm_last_debugon = 0;
unsigned long tm_last_savehist = 0;

// Define NTP Client to get time
WiFiUDP *ntpUDP = NULL;
NTPClient *timeClient = NULL;
String getTimeString(){
  char buf[16];
  if(!timeClient) return "00:00:00";
  sprintf(buf, "%02d:%02d:%02d", timeClient->getHours(), timeClient->getMinutes(), timeClient->getSeconds());
  return String(buf);
}
String getDateString(bool showDay=true){
  if(!timeClient)
    return showDay?"0000-00-00":"0000-00";
  time_t epochTime = timeClient->getEpochTime();
  struct tm *ptm = gmtime ((time_t *)&epochTime);
  int monthDay = ptm->tm_mday;
  int currentMonth = ptm->tm_mon+1;
  int currentYear = ptm->tm_year+1900;
  char buf[16];
  showDay?sprintf(buf, "%04d-%02d-%02d", currentYear, currentMonth, monthDay):sprintf(buf, "%04d-%02d", currentYear, currentMonth);
  return String(buf);
}
String weekDays[7]={"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"};
String getWeekdayString(){
  if(!timeClient) return "";
  return weekDays[timeClient->getDay()];
}
String getFullDateTime(){
  if(!timeClient) return "";
  return getDateString()+" ("+getWeekdayString()+") "+getTimeString();
}

String getBoardInfo(){
  FSInfo info;
  LittleFS.info(info);
  return String("VCC: ") + ESP.getVcc() + "; FreeHeap: " + ESP.getFreeHeap() + "; FlashSize: "+ESP.getFlashChipRealSize()+"; Speed: "+ESP.getFlashChipSpeed()
    +"; File system size (bytes): "+info.usedBytes+"/"+info.totalBytes;
}


// Saveable parameters
#define N_params 17
String g_params[N_params] = {"DARK_TH_LOW", "DARK_TH_HIGH", "DELAY_ON_MOV", "DELAY_ON_OCC", "OCC_TRIG_TH", "OCC_CONT_TH", "MOV_TRIG_TH", "MOV_CONT_TH", "LED_BEGIN", "LED_END", "GLIDE_TIME",
  "wifi_IP", "wifi_gateway", "wifi_subnet", "wifi_DNS1", "wifi_DNS2", "timezone"};
u32_t *g_pointer[N_params] = {&DARK_TH_LOW, &DARK_TH_HIGH, &DELAY_ON_MOV, &DELAY_ON_OCC, &OCC_TRIG_TH, &OCC_CONT_TH, &MOV_TRIG_TH, &MOV_CONT_TH, &LED_BEGIN, &LED_END, &GLIDE_TIME,
  (u32_t*)(ip_addr_t*)wifi_IP, (u32_t*)(ip_addr_t*)wifi_gateway, (u32_t*)(ip_addr_t*)wifi_subnet, (u32_t*)(ip_addr_t*)wifi_DNS1, (u32_t*)(ip_addr_t*)wifi_DNS2, (u32_t*)&timezone};
const int CONFIG_MAXSIZE = sizeof(int)*N_params/*g_params*/+(14*6+1)/*midnight start/stop times*/+(32+1)/*WIFI SSID*/+64/*WIFI password*/+16/*MD5 checksum*/+2/*end-of-string NULL byte*/;
bool set_value(String varname, unsigned int value){
  if(DEBUG)
    Serial.println("Setting '"+varname+"' to '"+value+"'");
  for(int x=0; x<N_params; x++)
    if(varname==g_params[x]){
      *g_pointer[x] = value;
      return true;
    }
  return false;
}
bool set_string(String varname, String value){
  if(DEBUG)
    Serial.println("Setting '"+varname+"' to '"+value+"'");
  if(varname=="wifi_ssid")
    wifi_ssid = value;
  else if(varname=="wifi_password")
    wifi_password = value;
  else if(varname.startsWith("wifi_")){
    int x;
    for(x=0; (x<N_params)&&(varname!=g_params[x]); x++);
    if(varname!=g_params[x]) return false;
    IPAddress ipa;
    if(!ipa.fromString(value)) ipa=IPAddress();
    *g_pointer[x] = (uint32_t)ipa;
  }else if(varname.startsWith("midnight_")){
    for(int x=0; x<7; x++){
      if(varname==String("midnight_start")+x){
        midnight_starts[x] = value;
        return true;
      }else if(varname==String("midnight_stop")+x){
        midnight_stops[x] = value;
        return true;
      }
    }
    return false;
  }else return false;
  return true;
}

void append_prune(String &buf, const String &s, int max_size){
  if(s.isEmpty()) return;
  while(buf.length() + s.length() > max_size){
    int posi = buf.indexOf('\n');
    if(posi<0) buf.clear();
    else buf.remove(0, posi+1);
  }
  buf.concat(s+"\n");
}

void open_logfile_auto_rotate(){
  if(!fp_hist.isFile())
    fp_hist = LittleFS.open("/0.log", "a");
  if(fp_hist.size()>LOGFILE_MAX_SIZE){  // rotate log
    fp_hist.close();
    for(int x=LOGFILE_MAX_NUM-1; x>=0; x--)
      LittleFS.rename(String(x)+".log", String(x+1)+".log");
    LittleFS.remove(String(LOGFILE_MAX_NUM)+".log");
    fp_hist = LittleFS.open("/0.log", "a");
  }
}

void log_event(const char *event){
  open_logfile_auto_rotate();
  String fullDateTime = getFullDateTime();
  fp_hist.printf("%s : %s\n", fullDateTime.c_str(), event);
  fp_hist.flush();
}

void md5(char *out, char *buf, int len) {
  md5_context_t ctx;
  MD5Init(&ctx);
  MD5Update(&ctx, (const uint8_t*)buf, len);
  MD5Final((uint8_t*)out, &ctx);
}

bool parse_combined_str(String s){
  int posi = s.indexOf('+');
  if(posi<0) return false;
  wifi_ssid = s.substring(0, posi);
  s = s.substring(posi+1);

  posi = s.indexOf('+');
  if(posi<0) return false;
  wifi_password = s.substring(0, posi);
  s = s.substring(posi+1);
  
  for(int x=0; x<7; x++){
    posi = s.indexOf('+');
    if(posi<0) return false;
    midnight_starts[x] = s.substring(0, posi);
    s = s.substring(posi+1);
    posi = s.indexOf('+');
    if(posi<0 && x<6) return false;
    midnight_stops[x] = posi<0?s:s.substring(0, posi);
    s = s.substring(posi+1);
  }
  return true;
}

bool set_times(String prefix, String s){
  if(DEBUG)
    Serial.println("Setting "+prefix+" to "+s);
  String tms[7];
  for(int x=0; x<7; x++){
    int posi = s.indexOf(' ');
    if(posi<0 && x<6) return false;
    tms[x] = posi<0?s:s.substring(0, posi);
    s = s.substring(posi+1);
  }
  for(int x=0; x<7; x++)
    if(!set_string(prefix+x, tms[x]))
      return false;
  return true;
}

bool save_file(const char *filename, const char *buf, size_t length){
  File fp = LittleFS.open(filename, "w");
  if(fp.isFile()){
    size_t n_written = fp.write((uint8_t*)buf, length);
    fp.close();
    return n_written==length;
  }
  return false;
}

bool save_config(){
  String combined_str = wifi_ssid+"+"+wifi_password;
  for(int x=0; x<7; x++)
    combined_str += ("+"+midnight_starts[x]+"+"+midnight_stops[x]);

  char buf[CONFIG_MAXSIZE];
  int posi = 0;
  for(int x=0; x<N_params; x++){
    *(unsigned int*)(&buf[posi]) = *g_pointer[x];
    posi += sizeof(unsigned int);
  }
  strcpy(&buf[posi], combined_str.c_str());
  posi += combined_str.length()+1;
  md5(&buf[posi], buf, posi);
  posi += 16;

  return save_file("/config.bin", buf, posi);
}

bool load_config(){
  char md5_comp[16];
  char buf[CONFIG_MAXSIZE];

  // read config file
  File fp = LittleFS.open("/config.bin", "r");
  if(!fp.isFile()) return false;
  int posi = fp.read((uint8_t*)buf, CONFIG_MAXSIZE);
  fp.close();
  if(!posi) return false;

  posi = N_params*sizeof(int);
  if(strlen(&buf[posi])>14*6+32+64)
    return false;

  String combined_str = String(&buf[posi]);
  posi += combined_str.length()+1;
  md5(md5_comp, buf, posi);
  if(memcmp(md5_comp, &buf[posi], 16)!=0)
    return false;

  posi = 0;
  for(int x=0; x<N_params; x++){
    *g_pointer[x] = *(unsigned int*)(&buf[posi]);
    posi += sizeof(unsigned int);
  }
  return parse_combined_str(combined_str);
}

void set_output(bool state){
  digitalWrite(PIN_CONTROL_OUTPUT, state?1:0);
  control_output = state;
  log_event(state?"light on":"light off");
  if(DEBUG) Serial.printf("Output = %s\n", state?"On":"Off");
}

void set_sensor(bool state){
  digitalWrite(PIN_MOTION_SENSOR, state?1:0);
  motion_sensor = state;
  log_event(state?"sensor on":"sensor off");
  if(DEBUG) Serial.printf("Sensor = %s\n", state?"On":"Off");
}

void set_onboard_led(bool state){
  digitalWrite(PIN_LED_MASTER, state?1:0);
  onboard_led = state;
  if(DEBUG) Serial.printf("Onboard LED = %s\n", state?"On":"Off");
}

void glide_onboard_led(bool state){
  log_event(state?"glide LED on":"glide LED off");
  if(GLIDE_TIME==0){
    set_onboard_led(state);
    onboard_led_level = state?LED_END:LED_BEGIN;
    analogWrite(PIN_LED_ADJ, onboard_led_level);
    return;
  }
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

void set_system_led_level(int value){
  int level = 255-value;
  level = min(255, max(0, level));
  analogWrite(LED_BUILTIN, level);
  SYSLED = value>0;
  if(DEBUG) Serial.printf("System LED level = %d\n", value);
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
  log_event("smartlight off");
  if(control_output) set_output(false);
  if(onboard_led) glide_onboard_led(false);
  is_smartlight_on = false;
}

bool is_midnight(){
  int weekday = (timeClient->getDay()+6)%7;
  String midnight_start = midnight_starts[weekday], midnight_stop = midnight_stops[weekday];
  int hours = timeClient->getHours(), minutes = timeClient->getMinutes();
  String midnight_time = getTimeString().substring(0, 5);
  if(midnight_start.isEmpty() || midnight_stop.isEmpty()) return false;
  if(midnight_stop > midnight_start) // midnight starts after 0am
    return midnight_time>=midnight_start && midnight_time<=midnight_stop;
  return midnight_time>=midnight_start || midnight_time<=midnight_stop;
}

void smartlight_on(){
  log_event("smartlight on");
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
  doc["datetime"] = getFullDateTime();
  doc["dbg_led"] = DEBUG;
  doc["sys_led"] = SYSLED;
  doc["ambient"] = ambient_level;
  doc["motion_sensor"] = motion_sensor;
  doc["onboard_led"] = onboard_led;
  doc["onboard_led_level"] = onboard_led_level;
  doc["control_output"] = control_output;
  doc["sensor_output"] = sensor_log;
  doc["is_midnight"] = is_midnight();
  doc["board_info"] = getBoardInfo();
  if(!svr_reply.isEmpty()){
    doc["svr_reply"] = svr_reply;
    svr_reply = "";
  }
  String output;
  serializeJson(doc, output);
  request->send(200, "text/html", output);
}

void handleStatic(AsyncWebServerRequest *request){
  DynamicJsonDocument doc(2048);
  for(int x=0; x<N_params; x++){
    if(g_params[x].startsWith("wifi_"))
      doc[g_params[x]] = IPAddress(*g_pointer[x]).toString();
    else
      doc[g_params[x]] = *g_pointer[x];
  }
  doc["wifi_ssid"] = wifi_ssid;
  doc["wifi_password"] = wifi_password;
  for(int x=0; x<7; x++){
    doc["midnight_start"+String(x)] = midnight_starts[x];
    doc["midnight_stop"+String(x)] = midnight_stops[x];
  }
  String output;
  serializeJson(doc, output);
  request->send(200, "text/html", output);
}

bool hotspot(){
  IPAddress apIP(172, 0, 0, 1);
  log_event("Creating hotspot with captive portal ...");
  Serial.println("Creating hotspot 'OpenSmartLight' ...");
  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(apIP, apIP, IPAddress(255, 255, 255, 0));
  WiFi.softAP(WIFI_NAME);
  Serial.print("Hotspot IP address: ");
  Serial.println(apIP);
  dnsServer = new DNSServer();
  dnsServer->setErrorReplyCode(DNSReplyCode::NoError);
  dnsServer->start(DNS_PORT, "*", apIP);
  initNTP();
  return false;
}

void initNTP(){
  if(timeClient){
    timeClient->end();
    delete timeClient;
  }
  if(ntpUDP){
    ntpUDP->stop();
    delete ntpUDP;
  }
  ntpUDP = new WiFiUDP();
  timeClient = new NTPClient(*ntpUDP, "pool.ntp.org", timezone*3600, 7200);
  timeClient->begin();
  timeClient->update();
  log_event((String("Synchronize time ")+(timeClient->isTimeSet()?"successfully":"failed")).c_str());
  Serial.printf("Current datetime = %s\n", getFullDateTime().c_str());
}

bool initWifi(){
  if(dnsServer){
    dnsServer->stop();
    delete dnsServer;
    dnsServer = NULL;
  }

  if(wifi_ssid.isEmpty())
    return hotspot();

  Serial.print("Connecting to WiFi ...");

  // Configures static IP address
  WiFi.mode(WIFI_STA);
  if (!WiFi.config(wifi_IP, wifi_gateway, wifi_subnet, wifi_DNS1.isSet()?wifi_DNS1:IPAddress(0), wifi_DNS2.isSet()?wifi_DNS2:IPAddress(0)))
    Serial.println("Static IP settings not set or incorrect: DHCP will be used");

  WiFi.begin(wifi_ssid, wifi_password);
  for(int x=0; x<=60; ++x){
    if(WiFi.status() == WL_CONNECTED) break;
    delay(1000);
    Serial.print(".");
  }
  if(WiFi.status() == WL_CONNECTED){
    log_event((String("Connected to WIFI, SSID=")+wifi_ssid).c_str());
    Serial.println("\nWiFi connected");
    Serial.println("IP address: ");
    Serial.println(WiFi.localIP());
  }else{
    log_event((String("Failed to connect to WIFI, SSID=")+wifi_ssid).c_str());
    Serial.println("\nUnable to connect to WiFi");
    return hotspot();
  }

  // Update time from Internet
  initNTP();
  return true;
}

String getFileList(){
  String ret;
  Dir dir = LittleFS.openDir("/");
  while (dir.next()){
    if(dir.fileName().endsWith(".log"))
      ret += dir.fileName()+" ";
  }
  ret.trim();
  return ret;
}

void deleteALL(){
  Dir dir = LittleFS.openDir("/");
  while (dir.next()){
    if(dir.fileName().endsWith(".log"))
      LittleFS.remove(dir.fileName());
  }
}

void initServer(){
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/static", handleStatic);
  server.on("/reboot", [](AsyncWebServerRequest *request) {reboot = true; request->send(200, "text/html", "");});
  server.on("/restart_wifi", [](AsyncWebServerRequest *request) {restart_wifi = true; request->send(200, "text/html", "");});
  server.on("/update_time", [](AsyncWebServerRequest *request) {update_ntp=true; request->send(200, "text/html", "");});
  server.on("/dbg_led_on", [](AsyncWebServerRequest *request) {set_debug_led(true);request->send(200, "text/html", "");});
  server.on("/dbg_led_off", [](AsyncWebServerRequest *request) {set_debug_led(false);request->send(200, "text/html", "");});
  server.on("/sys_led_on", [](AsyncWebServerRequest *request) {set_system_led(true);request->send(200, "text/html", "");});
  server.on("/sys_led_off", [](AsyncWebServerRequest *request) {set_system_led(false);request->send(200, "text/html", "");});
  server.on("/sys_led_level", [](AsyncWebServerRequest *request) {
    if(request->hasArg("level")){
      set_system_led_level(request->arg("level").toInt());
      request->send(200, "text/html", "");
    }else
      request->send(400, "text/html", "");
  });
  server.on("/log_history", [](AsyncWebServerRequest *request) {
    if(request->hasArg("delete")){
      String fn = request->arg("delete");
      if(fn=="ALL") deleteALL();
      else LittleFS.remove(fn);
    }
    request->send(200, "text/html", getFileList());
  });

  server.on("/control_output_on", [](AsyncWebServerRequest *request) {set_output(true);request->send(200, "text/html", "");});
  server.on("/control_output_off", [](AsyncWebServerRequest *request) {set_output(false);request->send(200, "text/html", "");});
  server.on("/motion_sensor_on", [](AsyncWebServerRequest *request) {set_sensor(true);request->send(200, "text/html", "");});
  server.on("/motion_sensor_off", [](AsyncWebServerRequest *request) {set_sensor(false);request->send(200, "text/html", "");});
  server.on("/glide_led_on", [](AsyncWebServerRequest *request) {do_glide=1;request->send(200, "text/html", "");});
  server.on("/glide_led_off", [](AsyncWebServerRequest *request) {do_glide=-1;request->send(200, "text/html", "");});
  server.on("/save_config", [](AsyncWebServerRequest *request) {request->send(200, "text/html", save_config()?"Success":"Failed");});
  server.on("/load_config", [](AsyncWebServerRequest *request) {request->send(200, "text/html", load_config()?"Success":"Failed");});
  server.on("/onboard_led_on", [](AsyncWebServerRequest *request) {set_onboard_led(true);request->send(200, "text/html", "");});
  server.on("/onboard_led_off", [](AsyncWebServerRequest *request) {set_onboard_led(false);request->send(200, "text/html", "");});
  server.on("/onboard_led_level", [](AsyncWebServerRequest *request) {
    if(request->hasArg("level")){
      set_onboard_led_level(request->arg("level").toInt());
      request->send(200, "text/html", "");
    }else
      request->send(400, "text/html", "");
  });
  server.on("/set_value", [](AsyncWebServerRequest *request) {
    request->send(200, "text/html", set_value(request->argName(0), request->arg((size_t)0).toInt())?"Success":"Failed");
  });
  server.on("/set_string", [](AsyncWebServerRequest *request) {
    request->send(200, "text/html", set_string(request->argName(0), request->arg((size_t)0))?"Success":"Failed");
  });
  server.on("/set_times", [](AsyncWebServerRequest *request){
    request->send(200, "text/html", set_times(request->argName(0), request->arg((int)0))?"Success":"Failed");
  });
  server.onNotFound([](AsyncWebServerRequest *request){request->send(404, "text/plain", "Content not found.");});
  server.serveStatic("/logs/", LittleFS, "/");
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

  // Initialize the file-system and create logfile
  LittleFS.begin();
  open_logfile_auto_rotate();

  // Initialize serial
  Serial.begin(115200);
  Serial.setTimeout(100L);
  Serial.println("\nSystem initialized:");

  // Load config file and history file if exist
  bool config_loaded = load_config();
  Serial.println(config_loaded?"Config file is valid and loaded!":"Config file NOT loaded!");
  log_event(config_loaded?"Config file loaded":"Config file NOT loaded");
  digitalWrite(LED_BUILTIN_AUX, config_loaded);


  initWifi();
  log_event("System started");
  initServer();
  digitalWrite(LED_BUILTIN, 1);
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
  if(tm_curr-tm_last_timesync>3600000*24 || update_ntp){
    bool res = timeClient->forceUpdate();
    svr_reply = res?"Success":"Failed";
    log_event((String("Force synchronize time ")+(res?"successfully":"failed")).c_str());
    if(DEBUG){
      Serial.printf("Update NTP %s\n", res?"successfully":"failed");
      Serial.printf("Current datetime = %s\n", getFullDateTime().c_str());
    }
    tm_last_timesync = tm_curr;
    update_ntp = false;
  }

  // Handle reboot
  if(reboot){
    log_event("System reboot");
    delay(200);
    ESP.restart();
  }

  // Handle restart WIFI
  if(restart_wifi){
    restart_wifi = false;
    delay(200);
    WiFi.disconnect(false, true);
    initWifi();
  }

  // Handle glide
  if(do_glide!=0){
    glide_onboard_led(do_glide>0);
    do_glide = 0;
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
    append_prune(sensor_log, s, SENSOR_LOG_MAX);
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
