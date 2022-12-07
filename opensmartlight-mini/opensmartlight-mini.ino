/*
 * This program is designed to work on LGT8F328P
 * for control ceiling light using HLK-HD1155D micro-motion sensor
 * Author: Wang Xuancong (2022.6)
 */

#define NOP __asm__ __volatile__ ("nop\n\t")
#include <WDT.h>
#include <avr/sleep.h>

#define LIGHT_TH_LOW  3000
#define LIGHT_TH_HIGH 3200
#define DELAY_ON_MOV  30000
#define DELAY_ON_OCC  20000
#define OCC_TRIG_TH  65530
#define OCC_CONT_TH  500
#define MOV_TRIG_TH  500
#define MOV_CONT_TH  250

// debug mode duration after RESET is pressed
#define DEBUG_DURATION 1800000

#define PIN_CONTROL D8
#define PIN_SENSOR D5

uint16_t adc_value;
bool is_light_on = false;
char DEBUG = 0;
extern volatile unsigned long timer0_millis;
int sleep_cnter=0;
unsigned long debug_start_millis = 0;

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

void led_flash(int mode=0){
  digitalWrite(LED_BUILTIN, 1);
  delay(mode?100:200);
  digitalWrite(LED_BUILTIN, 0);
  delay(mode?100:200);
}

inline void light_on(){
  digitalWrite(PIN_CONTROL, 1);
  if(DEBUG){
    digitalWrite(LED_BUILTIN, 1);
    Serial.println("Light on");
    Serial.flush();
  }
}

inline void light_off(){
  digitalWrite(PIN_CONTROL, 0);
  if(DEBUG){
    digitalWrite(LED_BUILTIN, 0);
    Serial.println("Light off");
    Serial.flush();
  }
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
  
  Serial.begin(115200);
  Serial.setTimeout(1000);  
  Serial.print("\nSystem initialized, light sensor = ");
  Serial.println(readAvgVolt(A0));
  Serial.println("Press RESET button to activate DEBUG mode for 30 minutes (press again to DEBUG dark mode); long-press RESET to restore reset functionality.");
  Serial.flush();
  delay(800);
}

char pc_int_cnt = 0;
unsigned long last_press = 0;
ISR(PCINT1_vect){
  cli();
  if((++pc_int_cnt)&1)
    last_press = millis();
  else{
    if(millis()-last_press>1000){  // long-click restore RESET button
      PCICR &= ~(1<<PCIE1);
      PCMSK1 &= ~(1<<PCINT14);
      PMX2 |= 0b10000000;
      PMX2 &= ~1;
      pinMode(PC6, OUTPUT);
      DEBUG = 0;
    }
    DEBUG = (DEBUG+1)%3;
    if(DEBUG) debug_start_millis = millis();
    digitalWrite(LED_BUILTIN, DEBUG&&is_light_on);
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

void auto_disable_debug(){
  if(millis()-debug_start_millis>DEBUG_DURATION)
    DEBUG = 0;
}

void loop() {
  // check light sensor
  light_off();
  sensor_off();
  if(readAvgVolt(A0)<LIGHT_TH_HIGH){
    sensor_off();
    if(DEBUG){
        Serial.println("Entering sleep ...");
        Serial.flush();
    }
    do{
      delay(4000);
      if(DEBUG){
        digitalWrite(LED_BUILTIN, (++sleep_cnter)&1);
        auto_disable_debug();
      }
    }while(readAvgVolt(A0)<LIGHT_TH_HIGH && DEBUG!=2);
    if(DEBUG){
      Serial.println("Exited sleep ...");
      Serial.flush();
    }
  }    


  // B. enter dark mode
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
    if(DEBUG)auto_disable_debug();
    if(is_light_on){  // when light is on
      if(Serial.available()){
        String s = Serial.readStringUntil('\n');
        if(DEBUG) Serial.println(s);
        if(s.startsWith("mov") && parse_output_value(s)>=MOV_CONT_TH){
          ul = millis()+DELAY_ON_MOV;
          if(DEBUG)led_flash(1);
        }else if(s.startsWith("occ") && parse_output_value(s)>=OCC_CONT_TH){
          ul = millis()+DELAY_ON_OCC;
          if(DEBUG)led_flash(0);
        }
        if(ul>elapse)
          elapse = ul;
      }else if(millis()>elapse){
        light_off();
        is_light_on=false;
        delay(500); // wait for light sensor to stablize
      }
    }else{  // when light is off
      if(Serial.available()){
        String s = Serial.readStringUntil('\n');
        if(DEBUG) Serial.println(s);
        if((s.startsWith("mov") && parse_output_value(s)>=MOV_TRIG_TH)
         || (s.startsWith("occ") && parse_output_value(s)>=OCC_TRIG_TH)){
          light_on();
          is_light_on=true;
          elapse = millis()+DELAY_ON_MOV;
        }
      }else if(readAvgVolt(A0)<LIGHT_TH_LOW && DEBUG!=2){ // return to day mode
        sensor_off();
        delay(1000);
        break;
      }
    }
  }
}
