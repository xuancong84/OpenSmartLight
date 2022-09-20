/*
 * This program is designed to work on LGT8F328P
 * for control ceiling light using HLK-HD1155D micro-motion sensor
 * Author: Wang Xuancong (2022.6)
 */

#define NOP __asm__ __volatile__ ("nop\n\t")
#include <WDT.h>
#include <avr/sleep.h>

#define LIGHT_TH_LOW  3800
#define LIGHT_TH_HIGH 4000
#define DELAY_ON_MOV  30000
#define DELAY_ON_OCC  20000
#define OCC_TRIG_TH  65530
#define OCC_CONT_TH  500
#define MOV_TRIG_TH  500
#define MOV_CONT_TH  250
#define CHECK_INTERVAL  125   // N*0.032 sec
#define LED_BEGIN 100
#define LED_END  120

// min day time that is considered as right before night begins, in the night, turning on other lights will also trigger day mode, but not for that long
#define MIN_DAY_LENGTH_MILLIS 3600000
// after this amount of time since night start, LED will be turned on instead of external light
#define MIN_TIME_AFTER_NIGHTFALL_MILLIS 5*3600000
// after this amount of time since night start, external light will be turned on
#define MAX_TIME_AFTER_NIGHTFALL_MILLIS 13*3600000

#define PIN_CONTROL D8
#define PIN_SENSOR D5
#define PIN_LED_GATE D9
#define PIN_LED_ADJ DAC0

uint16_t adc_value;
bool is_light_on = false;
bool DEBUG = false;
extern volatile unsigned long timer0_millis;
int sleep_cnter=0;
long day_start_time_millis=millis(), night_start_time_millis=millis();

void tx_to_pd6(char *str){
  char old = PMX0;
  char new1 = old|2;
  PMX0 |= 0x80;
  PMX0 = new1;
  Serial.print(str);
  Serial.flush();
  PMX0 |= 0x80;
  PMX0 = old;
}

void sensor_on(){
  HDR = 1;
  digitalWrite(D5, 1);
}

void sensor_off(){
  digitalWrite(D5, 0);
  HDR = 0;
}

bool is_led_on = false;
void led_on(){
  if(is_led_on) return;
  analogWrite(PIN_LED_ADJ, 0);
  digitalWrite(PIN_LED_GATE, 1);
  for(int x=LED_BEGIN; x<=LED_END; x++){
    analogWrite(PIN_LED_ADJ, x);
    delay(x>>1);
  }
  is_led_on = true;
  if(DEBUG){
    digitalWrite(LED_BUILTIN, 1);
    Serial.println("LED on");
    Serial.flush();
  }
}

void led_off(){
  if(!is_led_on) return;
  for(int x=LED_END; x>=LED_BEGIN; x--){
    analogWrite(PIN_LED_ADJ, x);
    delay(x>>1);
  }
  analogWrite(PIN_LED_ADJ, 0);
  digitalWrite(PIN_LED_GATE, 0);
  is_led_on = false;
  if(DEBUG){
    digitalWrite(LED_BUILTIN, 1);
    Serial.println("LED off");
    Serial.flush();
  }
}

inline void light_on(){
  digitalWrite(PIN_CONTROL, 1);
  is_light_on=true;
  if(DEBUG){
    digitalWrite(LED_BUILTIN, 1);
    Serial.println("Light on");
    Serial.flush();
  }
}

inline void light_off(){
  digitalWrite(PIN_CONTROL, 0);
  is_light_on=false;
  if(DEBUG){
    digitalWrite(LED_BUILTIN, 0);
    Serial.println("Light off");
    Serial.flush();
  }
}

void all_off(){
  analogWrite(PIN_LED_ADJ, 0);
  digitalWrite(PIN_LED_GATE, 0);
  light_off();
  sensor_off();
  is_led_on = false;
  is_light_on = false;
}

void smartlight_on(){
  long tm_after_nightfall = millis()-night_start_time_millis;
  if(tm_after_nightfall<0) tm_after_nightfall+=2147483647;
  if(tm_after_nightfall>MIN_TIME_AFTER_NIGHTFALL_MILLIS && tm_after_nightfall<MAX_TIME_AFTER_NIGHTFALL_MILLIS)
    led_on();
  else
    light_on();
}

void smartlight_off(){
  if(is_led_on)led_off();
  if(is_light_on)light_off();
}

int readAvgVolt(int pin){
  long sum = 0;
  for(int x=0;x<8;x++)
    sum += analogRead(pin);
  return (int)((sum+4)/8);
}

void setup() {
  // 0. Initialize
  delay(1000); // avoid soft brick

  // avoid floating ports
  for(int x=D2; x<=D13; x++){
    pinMode(x, OUTPUT);
    digitalWrite(x, 0);
  }
  for(int x=A0; x<=A7; x++){
    pinMode(x, OUTPUT);
    digitalWrite(x, 0);
  }

  // prevent PD6 from OC0A
  TCCR0B |= (1<<OC0AS);
  TCCR0B |= (1<<DTEN0);
  TCCR0A &= 0b00111111;

  // reuse RESET button as toggle DEBUG mode
  pinMode(PC6, INPUT_PULLUP);
  PMX2 |= 0b10000000;
  PMX2 |= 1;
  PCICR |= (1<<PCIE1);
  PCMSK1 |= (1<<PCINT14);

  // setup ambient light sensor
  pinMode(A0, INPUT_PULLUP);
  analogReference(DEFAULT);

  // setup D4 as DAC output, use VCC as reference
  pinMode(PIN_LED_ADJ, INPUT);
  DACON = 0b00001100;
  
  Serial.begin(115200);
  Serial.setTimeout(1000);
  Serial.print("\nSystem initialized, light sensor = ");
  Serial.println(readAvgVolt(A0));
  Serial.println("Press RESET button to toggle DEBUG/verbose mode; long-press RESET to restore reset functionality.");
  Serial.flush();
  delay(800);
}

char pc_int_cnt = 0;
unsigned long last_press = 0;
ISR(PCINT1_vect){
  cli();
  if(TIMSK2&0b00000010){
    if((++pc_int_cnt)&1)
      last_press = sleep_cnter;
    else{
      if(sleep_cnter!=last_press){  // long-click restore RESET button
        PCICR &= ~(1<<PCIE1);
        PCMSK1 &= ~(1<<PCINT14);
        PMX2 |= 0b10000000;
        PMX2 &= ~1;
        pinMode(PC6, OUTPUT);
        DEBUG = false;
      }
      DEBUG = !DEBUG;
      digitalWrite(LED_BUILTIN, DEBUG&&is_light_on);
    }
  }else{
    if((++pc_int_cnt)&1)
      last_press = millis();
    else{
      if(millis()-last_press>1000){  // long-click restore RESET button
        PCICR &= ~(1<<PCIE1);
        PCMSK1 &= ~(1<<PCINT14);
        PMX2 |= 0b10000000;
        PMX2 &= ~1;
        pinMode(PC6, OUTPUT);
        DEBUG = false;
      }
      DEBUG = !DEBUG;
      digitalWrite(LED_BUILTIN, DEBUG&&is_light_on);
    }
  }
  sei();
}

ISR(TIMER2_COMPA_vect){
  cli();
  sleep_disable();
  sei();
}

int parse_output_value(String s){
  char posi = s.lastIndexOf(' ');
  if(posi<0)return 0;
  return s.substring(posi+1).toInt();
}

void loop() {
  // check light sensor
  all_off();
  if(readAvgVolt(A0)<LIGHT_TH_HIGH){
    // A. enter day mode
    day_start_time_millis = millis();
    sensor_off();
    if(DEBUG){
        Serial.println("Entering sleep ...");
        Serial.flush();
    }
    do{
      delay(4000);
      if(DEBUG)
        digitalWrite(LED_BUILTIN, (++sleep_cnter)&1);
    }while(readAvgVolt(A0)<LIGHT_TH_HIGH);
    if(DEBUG){
      Serial.println("Exited sleep ...");
      Serial.flush();
    }
  }


  // B. enter dark mode
  if(millis()-day_start_time_millis>MIN_DAY_LENGTH_MILLIS)
    night_start_time_millis = millis();
  sensor_on();
  is_light_on = false;
  // reset timer0 counter
  // noInterrupts ();
  // timer0_millis = 0;
  // interrupts ();
  delay(30000); // wait for sensor to stabilize
  while(Serial.available())
    Serial.readStringUntil('\n');

  unsigned long elapse = millis(), ul=0;
  while(1){
    if(is_light_on){  // when light is on
      if(Serial.available()){
        String s = Serial.readStringUntil('\n');
        if(DEBUG) Serial.println(s);
        if(s.startsWith("mov") && parse_output_value(s)>=MOV_CONT_TH){
          ul = millis()+DELAY_ON_MOV;
        }else if(s.startsWith("occ") && parse_output_value(s)>=OCC_CONT_TH){
          ul = millis()+DELAY_ON_OCC;
        }
        if(ul>elapse)
          elapse = ul;
      }else if(millis()>elapse){
        smartlight_off();
        delay(500); // wait for light sensor to stablize
      }
    }else{  // when light is off
      if(Serial.available()){
        String s = Serial.readStringUntil('\n');
        if(DEBUG) Serial.println(s);
        if((s.startsWith("mov") && parse_output_value(s)>=MOV_TRIG_TH)
         || (s.startsWith("occ") && parse_output_value(s)>=OCC_TRIG_TH)){
          smartlight_on();
          elapse = millis()+DELAY_ON_MOV;          
        }
      }else if(readAvgVolt(A0)<LIGHT_TH_LOW){
        sensor_off();
        delay(1000);
        break;
      }
    }
  }
}
