// #include <EEPROM.h>
#include <ArduinoJson.h>
#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <ESP8266WebServer.h>
#include <NTPClient.h>
#include <WiFiUdp.h>
#include "./secret.h"

#define tzOffsetInSeconds 3600*8
#define PIN_CONTROL D2
#define PIN_MOTION_SENSOR D3
#define PIN_LED_MASTER D1
#define PIN_LED_ADJ D4
#define PIN_AMBIENT_PULLUP D7
#define PIN_AMBIENT_INPUT A0

int ambient_level;
bool dbg_led = false;

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

ESP8266WebServer server(80);
void handleRoot() {
  server.send(200, "text/html", R"(<h2>OpenSmartLight</h2>
<p>Date Time: <input type='text' id='datetime' size=24 readonly></p>
<p>Debug LED: <input type='text' id='dbg_led' readonly> <button onclick='GET("LED_DEBUG_on")'>On</button>&nbsp;
  <button onclick='GET("LED_DEBUG_off")'>Off</button>&nbsp;<button onclick='GET("LED_DEBUG_toggle")'>Toggle</button></p>
<p>Ambient Level: <input type='text' id='ambient' size=24 readonly></p>
<script>
function GET(url)
{
    var xmlHttp = new XMLHttpRequest();
    xmlHttp.open( 'GET', window.location+url, false ); // false for synchronous request
    xmlHttp.send( null );
    return xmlHttp.responseText;
}
window.onload = () => {
  obj = JSON.parse(GET('status'));
  for(const s of ['datetime', 'dbg_led', 'ambient'])
    document.getElementById(s).value = obj[s];
}
setInterval(window.onload, 1000);
</script>)"
    );
}

void handleStatus(){
  DynamicJsonDocument doc(2048);
  doc["datetime"] = getDateString()+" "+getTimeString();
  doc["dbg_led"] = dbg_led?"ON":"OFF";
  doc["ambient"] = ambient_level;
  String output;
  serializeJson(doc, output);
  server.send(200, "text/html", output);
}

void handleSave() {
  if (server.arg("pass") != "") {
    Serial.println(server.arg("pass"));
  }
}

void handle_dbg_led(){
  Serial.printf("DEBUG LED state = %d\n", dbg_led);
  digitalWrite(LED_BUILTIN_AUX, !dbg_led);
  server.send(200, "text/html", "");
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
  digitalWrite(LED_BUILTIN_AUX, true);
  Serial.println("\nWiFi connected");
  Serial.println("IP address: ");
  Serial.println(WiFi.localIP());
}

void initServer(){
  server.on("/", handleRoot);
  server.on("/status", handleStatus);
  server.on("/save", handleSave);
  server.on("/LED_DEBUG_on", []() {
    dbg_led = true;
    handle_dbg_led();
  });
  server.on("/LED_DEBUG_off", []() {
    dbg_led = false;
    handle_dbg_led();
  });
  server.on("/LED_DEBUG_toggle", []() {
    dbg_led = !dbg_led;
    handle_dbg_led();
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

void setup() {
  delay(1000);

  pinMode(PIN_CONTROL, OUTPUT);
  pinMode(PIN_MOTION_SENSOR, OUTPUT);
  pinMode(PIN_LED_MASTER, OUTPUT);
  pinMode(PIN_LED_ADJ, OUTPUT);
  pinMode(PIN_AMBIENT_PULLUP, INPUT_PULLUP);
  pinMode(PIN_AMBIENT_INPUT, INPUT);
  pinMode(LED_BUILTIN_AUX, OUTPUT);

  digitalWrite(LED_BUILTIN_AUX, false);
  
  Serial.begin(115200);
  Serial.println("\nSystem initialized:");
  handle_dbg_led();

  initWifi();

  // Update time from Internet
  timeClient.begin();
  timeClient.update();
  Serial.printf("Current datetime = %s %s\n", getDateString(), getTimeString());

  initServer();
}

unsigned long tm_last = millis();
void loop() {
  unsigned long tm_curr = millis();
  if(tm_curr-tm_last>1000){
    ambient_level = readAmbient();
    tm_last = tm_curr;
  }
  server.handleClient();
  delay(1);
}
