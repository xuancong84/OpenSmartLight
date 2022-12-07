#include <ESP8266WiFi.h>
#include <WiFiClient.h>
#include <ESP8266WebServer.h>
#include "./secret.h"

#define PIN_CONTROL D2
#define PIN_SENSOR D3
#define PIN_LED_MASTER D1
#define PIN_LED_ADJ D4
#define PIN_PHOTORESISTOR D7
#define PIN_AMBIENT_LIGHT A0

bool state = false;

/* Set these to your desired credentials. */
const char *ssid = WIFI_SSID;                 //Enter your WIFI ssid
const char *password = WIFI_PASSWORD;  //Enter your WIFI password

#if WIFI_STATICIP
// Set your Static IP address
IPAddress local_IP(192, 168, 50, 5);
IPAddress gateway(192, 168, 50, 1);
IPAddress subnet(255, 255, 255, 0);
IPAddress primaryDNS(8, 8, 8, 8);   //optional
IPAddress secondaryDNS(1, 1, 1, 1); //optional
#endif

ESP8266WebServer server(80);
void handleRoot() {
  server.send(200, "text/html", String(state?"LED is on<br>":"LED is off<br>")+
    String("<form action=\"/LED_BUILTIN_on\" method=\"get\" id=\"form1\"></form><button type=\"submit\" form=\"form1\" value=\"On\">On</button>"
    "<form action=\"/LED_BUILTIN_off\" method=\"get\" id=\"form2\"></form><button type=\"submit\" form=\"form2\" value=\"Off\">Off</button>"
    "<form action=\"/LED_BUILTIN_toggle\" method=\"get\" id=\"form3\"></form><button type=\"submit\" form=\"form3\" value=\"Off\">Toggle</button>"));
}

void handleSave() {
  if (server.arg("pass") != "") {
    Serial.println(server.arg("pass"));
  }
}

void act(){
  Serial.print("button state = ");
  Serial.println(state);
  digitalWrite(D1, state);
  digitalWrite(LED_BUILTIN, !state);
}


void setup() {
  delay(1000);
  pinMode(PIN_CONTROL, OUTPUT);
  pinMode(PIN_SENSOR, OUTPUT);
  pinMode(PIN_LED_MASTER, OUTPUT);
  pinMode(PIN_LED_ADJ, OUTPUT);
  pinMode(PIN_PHOTORESISTOR, OUTPUT);
  pinMode(PIN_AMBIENT_LIGHT, INPUT);
  pinMode(LED_BUILTIN_AUX, OUTPUT);

  digitalWrite(LED_BUILTIN_AUX, true);
  
  delay(1000);
  Serial.begin(115200);
  Serial.println("\nSystem initialized:");
  act();
  Serial.print("Configuring access point...");

#if WIFI_STATICIP
  // Configures static IP address
  if (!WiFi.config(local_IP, gateway, subnet, primaryDNS, secondaryDNS))
    Serial.println("Static IP settings incorrect: failed to configure!");
#endif

  WiFi.begin(ssid, password);
  int x = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(1000);
    Serial.print(".");
    if(++x%32==0)Serial.println();
  }
  digitalWrite(LED_BUILTIN_AUX, false);
  Serial.println("");
  Serial.println("WiFi connected");
  Serial.println("IP address: ");
  Serial.println(WiFi.localIP());
  server.on("/", handleRoot);
  server.on("/save", handleSave);
  server.begin();
  Serial.println("HTTP server started");
  server.on("/LED_BUILTIN_on", []() {
    state = true;
    act();
    handleRoot();
  });
  server.on("/LED_BUILTIN_off", []() {
    state = false;
    act();
    handleRoot();
  });
  server.on("/LED_BUILTIN_toggle", []() {
    state = !state;
    act();
    handleRoot();
  });
}

void loop() {
  server.handleClient();
}
