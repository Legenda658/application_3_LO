#include <LiquidCrystal.h>
#include <DHT.h>
#include <Wire.h>
#include <TimeLib.h>
#define PIN_RS 6
#define PIN_EN 7
#define PIN_DB4 8
#define PIN_DB5 9
#define PIN_DB6 10
#define PIN_DB7 11
#define SOIL_MOISTURE_PIN A0
#define POTENTIOMETER_PIN A1
#define DHT_PIN 13
#define BUTTON_PIN 12
#define RELAY_1_PIN 5
#define RELAY_2_PIN 4
#define RELAY_3_PIN 3
#define RELAY_4_PIN 2
#define LED_RELAY RELAY_1_PIN
#define CURTAINS_RELAY RELAY_2_PIN
#define PUMP_RELAY RELAY_3_PIN
#define FAN_RELAY RELAY_4_PIN
#define DHT_TYPE DHT22
#define DISPLAY_INTERVAL 5000
#define TIME_UPDATE_INTERVAL 1000
#define LONG_PRESS_DURATION 3000
enum ProgramState {
  SETUP_TEMPERATURE,
  SETUP_TEMP_TOLERANCE,
  SETUP_SOIL_MOISTURE,
  SETUP_SOIL_TOLERANCE,
  SETUP_CURTAINS_OPEN_TIME,
  SETUP_CURTAINS_CLOSE_TIME,
  SETUP_LAMP_ON_TIME,
  SETUP_LAMP_OFF_TIME,
  NORMAL_OPERATION
};
enum DisplayMode {
  TIME_DATE,
  SOIL_MOISTURE,
  AIR_DATA,
  DEVICES_STATE,
  PUMP_FAN_STATE
};
LiquidCrystal lcd(PIN_RS, PIN_EN, PIN_DB4, PIN_DB5, PIN_DB6, PIN_DB7);
DHT dht(DHT_PIN, DHT_TYPE);
ProgramState currentState = SETUP_TEMPERATURE;
DisplayMode currentDisplayMode = SOIL_MOISTURE;
int targetTemperature = 25;
int tempTolerance = 3;
int targetSoilMoisture = 50;
int soilTolerance = 5;
int curtainsOpenHour = 8;
int curtainsOpenMinute = 0;
int curtainsCloseHour = 20;
int curtainsCloseMinute = 0;
int lampOnHour = 8;
int lampOnMinute = 30;
int lampOffHour = 21;
int lampOffMinute = 0;
bool isTimeSet = false;
time_t currentTime = 0;
bool lastButtonState = HIGH;
bool buttonState = HIGH;
unsigned long lastDebounceTime = 0;
unsigned long debounceDelay = 50;
unsigned long buttonPressStartTime = 0;
bool buttonLongPressed = false;
bool isButtonHeld = false;
int drySoilValue = 1000;
int wetSoilValue = 200;
unsigned long lastDisplayChange = 0;
unsigned long lastTimeUpdate = 0;
unsigned long lastTimeSync = 0;
bool ledState = false;
bool curtainsState = false;
bool pumpState = false;
bool fanState = false;
bool showTemperatureWarning = false;
bool showSoilMoistureWarning = false;
int lastDisplayedTemp = -99;
int lastDisplayedTol = -99;
int lastDisplayedMoist = -99;
int lastDisplayedSoilTol = -99;
int lastCurtainsOpenHour = -99;
int lastCurtainsOpenMinute = -99;
int lastCurtainsCloseHour = -99;
int lastCurtainsCloseMinute = -99;
int lastLampOnHour = -99;
int lastLampOnMinute = -99;
int lastLampOffHour = -99;
int lastLampOffMinute = -99;
String lastSetupCommand = "";
bool allParamsSet = false;
bool paramsSetFromPC = false;
void setup() {
  Serial.begin(9600);
  Wire.begin();
  lcd.begin(16, 2);
  dht.begin();
  pinMode(RELAY_1_PIN, OUTPUT);
  pinMode(RELAY_2_PIN, OUTPUT);
  pinMode(RELAY_3_PIN, OUTPUT);
  pinMode(RELAY_4_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  digitalWrite(RELAY_1_PIN, HIGH);
  digitalWrite(RELAY_2_PIN, HIGH);
  digitalWrite(RELAY_3_PIN, HIGH);
  digitalWrite(RELAY_4_PIN, HIGH);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Waiting for");
  lcd.setCursor(0, 1);
  lcd.print("setup...");
  waitForTimeSync();
  if (paramsSetFromPC) {
    currentState = NORMAL_OPERATION;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("PC setup done!");
    lcd.setCursor(0, 1);
    lcd.print("Auto start...");
    delay(1500);
    displaySoilMoistureData();
  } else {
    displaySetupScreen();
  }
}
void loop() {
  processSerialCommands();
  if (paramsSetFromPC) {
    currentState = NORMAL_OPERATION;
  }
  handleButton();
  updateTime();
  if (currentState == NORMAL_OPERATION) {
    normalOperationLoop();
  } else {
    setupParametersLoop();
  }
}
void updateTime() {
  if (isTimeSet) {
    if (millis() - lastTimeUpdate >= TIME_UPDATE_INTERVAL) {
      lastTimeUpdate = millis();
      currentTime++;
      if (currentDisplayMode == TIME_DATE) {
        displayTimeDate();
      }
    }
  } else if (currentDisplayMode == TIME_DATE) {
    static unsigned long lastTimeMessageUpdate = 0;
    if (millis() - lastTimeMessageUpdate >= 1000) {
      lastTimeMessageUpdate = millis();
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Waiting for time");
      lcd.setCursor(0, 1);
      lcd.print("synchronization");
    }
  }
}
void handleButton() {
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastButtonState) {
    lastDebounceTime = millis();
  }
  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (reading != buttonState) {
      buttonState = reading;
      if (buttonState == LOW) {
        buttonPressStartTime = millis();
        isButtonHeld = true;
        buttonLongPressed = false;
      } 
      else if (buttonState == HIGH && isButtonHeld) {
        isButtonHeld = false;
        if (!buttonLongPressed) {
          handleShortButtonPress();
        }
      }
    }
  }
  if (isButtonHeld && !buttonLongPressed && millis() - buttonPressStartTime >= LONG_PRESS_DURATION) {
    buttonLongPressed = true;
    handleLongButtonPress();
  }
  lastButtonState = reading;
}
void handleShortButtonPress() {
  if (currentState == NORMAL_OPERATION) {
    lastDisplayChange = millis();
    switchToNextDisplay();
  } else {
    moveToNextSetupState();
  }
}
void handleLongButtonPress() {
  if (currentState == NORMAL_OPERATION) {
    Serial.println("Long button press - switching to time display");
    if (currentDisplayMode == TIME_DATE) {
      currentDisplayMode = SOIL_MOISTURE;
      displaySoilMoistureData();
    } else {
      currentDisplayMode = TIME_DATE;
      displayTimeDate();
    }
  }
}
void processSerialCommands() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    command.toUpperCase();
    if (command.startsWith("TIME:")) {
      setTimeFromString(command.substring(5));
      isTimeSet = true;
      Serial.println("TIME_OK");
    } else if (command.startsWith("SET:TEMP:")) {
      targetTemperature = command.substring(9).toInt();
      Serial.println("TEMP_OK");
      paramsSetFromPC = true;
    } else if (command.startsWith("SET:TEMP_TOL:")) {
      tempTolerance = command.substring(13).toInt();
      Serial.println("TEMP_TOL_OK");
      paramsSetFromPC = true;
    } else if (command.startsWith("SET:SOIL:")) {
      targetSoilMoisture = command.substring(9).toInt();
      Serial.println("SOIL_OK");
      paramsSetFromPC = true;
    } else if (command.startsWith("SET:SOIL_TOL:")) {
      soilTolerance = command.substring(13).toInt();
      Serial.println("SOIL_TOL_OK");
      paramsSetFromPC = true;
    } else if (command.startsWith("SET:CURT_OPEN:")) {
      int h = command.substring(14, 16).toInt();
      int m = command.substring(17, 19).toInt();
      curtainsOpenHour = h; curtainsOpenMinute = m;
      Serial.println("CURT_OPEN_OK");
      paramsSetFromPC = true;
    } else if (command.startsWith("SET:CURT_CLOSE:")) {
      int h = command.substring(15, 17).toInt();
      int m = command.substring(18, 20).toInt();
      curtainsCloseHour = h; curtainsCloseMinute = m;
      Serial.println("CURT_CLOSE_OK");
      paramsSetFromPC = true;
    } else if (command.startsWith("SET:LAMP_ON:")) {
      int h = command.substring(12, 14).toInt();
      int m = command.substring(15, 17).toInt();
      lampOnHour = h; lampOnMinute = m;
      Serial.println("LAMP_ON_OK");
      paramsSetFromPC = true;
    } else if (command.startsWith("SET:LAMP_OFF:")) {
      int h = command.substring(13, 15).toInt();
      int m = command.substring(16, 18).toInt();
      lampOffHour = h; lampOffMinute = m;
      Serial.println("LAMP_OFF_OK");
      paramsSetFromPC = true;
    }
    delay(100);
  }
}
void setTimeFromString(String timeData) {
  int yearVal = timeData.substring(0, 4).toInt();
  int monthVal = timeData.substring(5, 7).toInt();
  int dayVal = timeData.substring(8, 10).toInt();
  int hourVal = timeData.substring(11, 13).toInt();
  int minuteVal = timeData.substring(14, 16).toInt();
  int secondVal = timeData.substring(17, 19).toInt();
  setTime(hourVal, minuteVal, secondVal, dayVal, monthVal, yearVal);
  currentTime = now();
  isTimeSet = true;
  lastTimeSync = millis();
  Serial.print("Time set to: ");
  Serial.println(timeData);
  if (currentDisplayMode == TIME_DATE) {
    displayTimeDate();
  }
}
void waitForTimeSync() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Waiting for time");
  lcd.setCursor(0, 1);
  lcd.print("synchronization");
  Serial.println("Waiting for time synchronization...");
  Serial.println("Send command TIME:YYYY-MM-DD HH:MM:SS");
  while (!isTimeSet) {
    if (Serial.available() > 0) {
      String command = Serial.readStringUntil('\n');
      if (command.startsWith("TIME:")) {
        String timeData = command.substring(5);
        setTimeFromString(timeData);
        break;
      }
    }
    delay(100);
  }
}
void switchToNextDisplay() {
  switch (currentDisplayMode) {
    case TIME_DATE:
      currentDisplayMode = SOIL_MOISTURE;
      displaySoilMoistureData();
      break;
    case SOIL_MOISTURE:
      currentDisplayMode = AIR_DATA;
      displayDHTData();
      break;
    case AIR_DATA:
      currentDisplayMode = DEVICES_STATE;
      displayDevicesState();
      break;
    case DEVICES_STATE:
      currentDisplayMode = PUMP_FAN_STATE;
      displayPumpFanState();
      break;
    case PUMP_FAN_STATE:
      currentDisplayMode = SOIL_MOISTURE;
      displaySoilMoistureData();
      break;
  }
}
void displayTimeDate() {
  if (!isTimeSet) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Waiting for time");
    lcd.setCursor(0, 1);
    lcd.print("synchronization");
    return;
  }
  int yearVal = year(currentTime);
  int monthVal = month(currentTime);
  int dayVal = day(currentTime);
  int hourVal = hour(currentTime);
  int minuteVal = minute(currentTime);
  int secondVal = second(currentTime);
  lcd.clear();
  lcd.setCursor(4, 0);
  if (hourVal < 10) lcd.print("0");
  lcd.print(hourVal);
  lcd.print(":");
  if (minuteVal < 10) lcd.print("0");
  lcd.print(minuteVal);
  lcd.print(":");
  if (secondVal < 10) lcd.print("0");
  lcd.print(secondVal);
  lcd.setCursor(2, 1);
  lcd.print(yearVal);
  lcd.print("-");
  if (monthVal < 10) lcd.print("0");
  lcd.print(monthVal);
  lcd.print("-");
  if (dayVal < 10) lcd.print("0");
  lcd.print(dayVal);
  Serial.print("Current time: ");
  Serial.print(yearVal);
  Serial.print("-");
  if (monthVal < 10) Serial.print("0");
  Serial.print(monthVal);
  Serial.print("-");
  if (dayVal < 10) Serial.print("0");
  Serial.print(dayVal);
  Serial.print(" ");
  if (hourVal < 10) Serial.print("0");
  Serial.print(hourVal);
  Serial.print(":");
  if (minuteVal < 10) Serial.print("0");
  Serial.print(minuteVal);
  Serial.print(":");
  if (secondVal < 10) Serial.print("0");
  Serial.println(secondVal);
}
void displaySoilMoistureData() {
  int soilMoistureRaw = analogRead(SOIL_MOISTURE_PIN);
  int soilMoisturePercent = map(soilMoistureRaw, drySoilValue, wetSoilValue, 0, 100);
  soilMoisturePercent = constrain(soilMoisturePercent, 0, 100);
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Soil moisture:");
  lcd.setCursor(0, 1);
  lcd.print(soilMoisturePercent);
  lcd.print("%");
  if (showSoilMoistureWarning) {
    lcd.setCursor(7, 1);
    lcd.print(" HIGH!");
  }
  Serial.print("Soil moisture: ");
  Serial.print(soilMoisturePercent);
  Serial.println("%");
}
void displayDHTData() {
  float humidity = dht.readHumidity();
  float temperature = dht.readTemperature();
  if (isnan(humidity) || isnan(temperature)) {
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("DHT read failed");
    Serial.println("Failed to read from DHT sensor!");
    return;
  }
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Humidity: ");
  lcd.print(humidity, 1);
  lcd.print("%");
  lcd.setCursor(0, 1);
  lcd.print("Temp: ");
  lcd.print(temperature, 1);
  lcd.print("\xDF""C");
  if (showTemperatureWarning) {
    lcd.setCursor(15, 1);
    lcd.print("!");
  }
  Serial.print("Humidity: ");
  Serial.print(humidity);
  Serial.print("% ");
  Serial.print("Temperature: ");
  Serial.print(temperature);
  Serial.println("°C");
}
void displayDevicesState() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Lamp: ");
  lcd.print(ledState ? "ON" : "OFF");
  lcd.setCursor(0, 1);
  lcd.print("Curtains: ");
  lcd.print(curtainsState ? "OPEN" : "CLOSED");
  Serial.println("Device states:");
  Serial.print("Lamp: ");
  Serial.println(ledState ? "ON" : "OFF");
  Serial.print("Curtains: ");
  Serial.println(curtainsState ? "OPEN" : "CLOSED");
}
void displayPumpFanState() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Pump: ");
  lcd.print(pumpState ? "ON" : "OFF");
  lcd.setCursor(0, 1);
  lcd.print("Fan: ");
  lcd.print(fanState ? "ON" : "OFF");
  Serial.print("Pump: ");
  Serial.println(pumpState ? "ON" : "OFF");
  Serial.print("Fan: ");
  Serial.println(fanState ? "ON" : "OFF");
}
void displaySetupScreen() {
  resetDisplayCache(); 
  switch (currentState) {
    case SETUP_TEMPERATURE:
      displaySetupTemperature();
      break;
    case SETUP_TEMP_TOLERANCE:
      displaySetupTempTolerance();
      break;
    case SETUP_SOIL_MOISTURE:
      displaySetupSoilMoisture();
      break;
    case SETUP_SOIL_TOLERANCE:
      displaySetupSoilTolerance();
      break;
    case SETUP_CURTAINS_OPEN_TIME:
      displaySetupCurtainsOpenTime();
      break;
    case SETUP_CURTAINS_CLOSE_TIME:
      displaySetupCurtainsCloseTime();
      break;
    case SETUP_LAMP_ON_TIME:
      displaySetupLampOnTime();
      break;
    case SETUP_LAMP_OFF_TIME:
      displaySetupLampOffTime();
      break;
    default:
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Setup mode");
      break;
  }
}
void normalOperationLoop() {
  controlDevices();
  if (currentDisplayMode != TIME_DATE) {
    if (millis() - lastDisplayChange >= DISPLAY_INTERVAL) {
      lastDisplayChange = millis();
      switchToNextDisplay();
    }
  }
}
void setupParametersLoop() {
  static unsigned long lastMenuUpdate = 0;
  const unsigned long menuUpdateDelay = 250; 
  if (millis() - lastMenuUpdate < menuUpdateDelay) {
    return;
  }
  static int lastPotValues[5] = {0};
  static int potIndex = 0;
  static int lastProcessedValue = -100;
  int rawPotValue = analogRead(POTENTIOMETER_PIN);
  lastPotValues[potIndex] = rawPotValue;
  potIndex = (potIndex + 1) % 5;
  int potSum = 0;
  for (int i = 0; i < 5; i++) {
    potSum += lastPotValues[i];
  }
  int potValue = potSum / 5;
  if (abs(potValue - lastProcessedValue) > 10) {
    lastProcessedValue = potValue;
    lastMenuUpdate = millis();
    switch (currentState) {
      case SETUP_TEMPERATURE:
        targetTemperature = map(potValue, 0, 1023, 10, 40);
        displaySetupTemperature();
        break;
      case SETUP_TEMP_TOLERANCE:
        tempTolerance = map(potValue, 0, 1023, 1, 6);
        displaySetupTempTolerance();
        break;
      case SETUP_SOIL_MOISTURE:
        targetSoilMoisture = map(potValue, 0, 1023, 16, 100);
        displaySetupSoilMoisture();
        break;
      case SETUP_SOIL_TOLERANCE:
        soilTolerance = map(potValue, 0, 1023, 1, 10);
        displaySetupSoilTolerance();
        break;
      case SETUP_CURTAINS_OPEN_TIME:
        setupTimeFromPot(potValue, &curtainsOpenHour, &curtainsOpenMinute);
        displaySetupCurtainsOpenTime();
        break;
      case SETUP_CURTAINS_CLOSE_TIME:
        setupTimeFromPot(potValue, &curtainsCloseHour, &curtainsCloseMinute);
        displaySetupCurtainsCloseTime();
        break;
      case SETUP_LAMP_ON_TIME:
        setupTimeFromPot(potValue, &lampOnHour, &lampOnMinute);
        displaySetupLampOnTime();
        break;
      case SETUP_LAMP_OFF_TIME:
        setupTimeFromPot(potValue, &lampOffHour, &lampOffMinute);
        displaySetupLampOffTime();
        break;
    }
  }
}
void setupTimeFromPot(int potValue, int *hour, int *minute) {
  int totalMinutes = map(potValue, 0, 1023, 0, 47);
  *hour = totalMinutes / 2;
  *minute = (totalMinutes % 2) * 30;
}
void displaySetupTemperature() {
  if (lastDisplayedTemp != targetTemperature) {
    lastDisplayedTemp = targetTemperature;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Set temp. (C):");
    lcd.setCursor(0, 1);
    lcd.print(targetTemperature);
    lcd.print(" C");
  }
}
void displaySetupTempTolerance() {
  if (lastDisplayedTol != tempTolerance) {
    lastDisplayedTol = tempTolerance;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Temp. tolerance:");
    lcd.setCursor(0, 1);
    lcd.print("+/- ");
    lcd.print(tempTolerance);
    lcd.print(" C");
  }
}
void displaySetupSoilMoisture() {
  if (lastDisplayedMoist != targetSoilMoisture) {
    lastDisplayedMoist = targetSoilMoisture;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Soil moisture:");
    lcd.setCursor(0, 1);
    lcd.print(targetSoilMoisture);
    lcd.print("%");
  }
}
void displaySetupSoilTolerance() {
  if (lastDisplayedSoilTol != soilTolerance) {
    lastDisplayedSoilTol = soilTolerance;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Moist. tolerance:");
    lcd.setCursor(0, 1);
    lcd.print("+/- ");
    lcd.print(soilTolerance);
    lcd.print("%");
  }
}
void displaySetupCurtainsOpenTime() {
  if (lastCurtainsOpenHour != curtainsOpenHour || lastCurtainsOpenMinute != curtainsOpenMinute) {
    lastCurtainsOpenHour = curtainsOpenHour;
    lastCurtainsOpenMinute = curtainsOpenMinute;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Curtains open:");
    lcd.setCursor(0, 1);
    printTime(curtainsOpenHour, curtainsOpenMinute);
  }
}
void displaySetupCurtainsCloseTime() {
  if (lastCurtainsCloseHour != curtainsCloseHour || lastCurtainsCloseMinute != curtainsCloseMinute) {
    lastCurtainsCloseHour = curtainsCloseHour;
    lastCurtainsCloseMinute = curtainsCloseMinute;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Curtains close:");
    lcd.setCursor(0, 1);
    printTime(curtainsCloseHour, curtainsCloseMinute);
  }
}
void displaySetupLampOnTime() {
  if (lastLampOnHour != lampOnHour || lastLampOnMinute != lampOnMinute) {
    lastLampOnHour = lampOnHour;
    lastLampOnMinute = lampOnMinute;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Lamp on time:");
    lcd.setCursor(0, 1);
    printTime(lampOnHour, lampOnMinute);
  }
}
void displaySetupLampOffTime() {
  if (lastLampOffHour != lampOffHour || lastLampOffMinute != lampOffMinute) {
    lastLampOffHour = lampOffHour;
    lastLampOffMinute = lampOffMinute;
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Lamp off time:");
    lcd.setCursor(0, 1);
    printTime(lampOffHour, lampOffMinute);
  }
}
void printTime(int hour, int minute) {
  if (hour < 10) lcd.print("0");
  lcd.print(hour);
  lcd.print(":");
  if (minute < 10) lcd.print("0");
  lcd.print(minute);
}
void controlDevices() {
  int soilMoistureRaw = analogRead(SOIL_MOISTURE_PIN);
  int soilMoisturePercent = map(soilMoistureRaw, drySoilValue, wetSoilValue, 0, 100);
  soilMoisturePercent = constrain(soilMoisturePercent, 0, 100);
  if (soilMoisturePercent < (targetSoilMoisture - soilTolerance)) {
    if (!pumpState) {
      pumpState = true;
      digitalWrite(PUMP_RELAY, LOW); 
      Serial.println("Pump turned ON: low soil moisture");
    }
  } else if (soilMoisturePercent >= targetSoilMoisture) {
    if (pumpState) {
      pumpState = false;
      digitalWrite(PUMP_RELAY, HIGH); 
      Serial.println("Pump turned OFF: target soil moisture reached");
    }
  }
  showSoilMoistureWarning = (soilMoisturePercent > (targetSoilMoisture + soilTolerance));
  float temperature = dht.readTemperature();
  if (!isnan(temperature)) {
    if (temperature > (targetTemperature + tempTolerance)) {
      if (!fanState) {
        fanState = true;
        digitalWrite(FAN_RELAY, LOW); 
        Serial.println("Fan turned ON: high temperature");
      }
    } else if (temperature <= targetTemperature) {
      if (fanState) {
        fanState = false;
        digitalWrite(FAN_RELAY, HIGH); 
        Serial.println("Fan turned OFF: target temperature reached");
      }
    }
    showTemperatureWarning = (temperature > (targetTemperature + tempTolerance));
  }
  if (isTimeSet) {
    int currentHour = hour(currentTime);
    int currentMinute = minute(currentTime);
    int currentTimeInMinutes = currentHour * 60 + currentMinute;
    int curtainsOpenTimeInMinutes = curtainsOpenHour * 60 + curtainsOpenMinute;
    int curtainsCloseTimeInMinutes = curtainsCloseHour * 60 + curtainsCloseMinute;
    bool shouldCurtainsBeOpen;
    if (curtainsOpenTimeInMinutes < curtainsCloseTimeInMinutes) {
      shouldCurtainsBeOpen = (currentTimeInMinutes >= curtainsOpenTimeInMinutes && 
                              currentTimeInMinutes < curtainsCloseTimeInMinutes);
    } else {
      shouldCurtainsBeOpen = (currentTimeInMinutes >= curtainsOpenTimeInMinutes || 
                              currentTimeInMinutes < curtainsCloseTimeInMinutes);
    }
    if (shouldCurtainsBeOpen != curtainsState) {
      curtainsState = shouldCurtainsBeOpen;
      digitalWrite(CURTAINS_RELAY, curtainsState ? LOW : HIGH);
      Serial.print("Curtains ");
      Serial.println(curtainsState ? "OPEN" : "CLOSED");
    }
    int lampOnTimeInMinutes = lampOnHour * 60 + lampOnMinute;
    int lampOffTimeInMinutes = lampOffHour * 60 + lampOffMinute;
    bool shouldLampBeOn;
    if (lampOnTimeInMinutes < lampOffTimeInMinutes) {
      shouldLampBeOn = (currentTimeInMinutes >= lampOnTimeInMinutes && 
                        currentTimeInMinutes < lampOffTimeInMinutes);
    } else {
      shouldLampBeOn = (currentTimeInMinutes >= lampOnTimeInMinutes || 
                        currentTimeInMinutes < lampOffTimeInMinutes);
    }
    if (shouldLampBeOn != ledState) {
      ledState = shouldLampBeOn;
      digitalWrite(LED_RELAY, ledState ? LOW : HIGH);
      Serial.print("Lamp ");
      Serial.println(ledState ? "ON" : "OFF");
    }
  }
}
void moveToNextSetupState() {
  lcd.clear();
  switch (currentState) {
    case SETUP_TEMPERATURE:
      currentState = SETUP_TEMP_TOLERANCE;
      break;
    case SETUP_TEMP_TOLERANCE:
      currentState = SETUP_SOIL_MOISTURE;
      break;
    case SETUP_SOIL_MOISTURE:
      currentState = SETUP_SOIL_TOLERANCE;
      break;
    case SETUP_SOIL_TOLERANCE:
      currentState = SETUP_CURTAINS_OPEN_TIME;
      break;
    case SETUP_CURTAINS_OPEN_TIME:
      currentState = SETUP_CURTAINS_CLOSE_TIME;
      break;
    case SETUP_CURTAINS_CLOSE_TIME:
      currentState = SETUP_LAMP_ON_TIME;
      break;
    case SETUP_LAMP_ON_TIME:
      currentState = SETUP_LAMP_OFF_TIME;
      break;
    case SETUP_LAMP_OFF_TIME:
      currentState = NORMAL_OPERATION;
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Setup complete!");
      lcd.setCursor(0, 1);
      lcd.print("Starting system");
      delay(2000);
      displaySoilMoistureData();
      return; 
      break;
  }
  delay(500); 
  displaySetupScreen();
}
void resetDisplayCache() {
  lastDisplayedTemp = -99;
  lastDisplayedTol = -99;
  lastDisplayedMoist = -99;
  lastDisplayedSoilTol = -99;
  lastCurtainsOpenHour = -99;
  lastCurtainsOpenMinute = -99;
  lastCurtainsCloseHour = -99;
  lastCurtainsCloseMinute = -99;
  lastLampOnHour = -99;
  lastLampOnMinute = -99;
  lastLampOffHour = -99;
  lastLampOffMinute = -99;
} 