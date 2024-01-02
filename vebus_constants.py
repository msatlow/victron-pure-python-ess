

F_Request_DC = 0
F_Request_AC_L1 = 1
F_Request_AC_L2 = 2
F_Request_AC_L3 = 3
F_Request_AC_L4 = 4
F_Request_MasterMultiLED = 5
F_Request_Snapshot = 6
F_Reset_VEBus_devices = 8
F_Send_BOL = 9



RAMIDUMainsRMS                 = 0
RAMIDIMainsRMS                 = 1
RAMIDUInverterRMS              = 2
RAMIDIINverterRMS              = 3
RAMIDUBat                      = 4
RAMIDIBat                      = 5
RAMIDUBatRMS                   = 6 # RMS=value of ripple voltage
RAMIDInverterPeriodTime        = 7 # time-base 0.1s
RAMIDMainsPeriodTime           = 8 # time-base 0.1s
RAMIDSignedACLoadCurrent       = 9
RAMIDVirtualSwitchPosition     = 10
RAMIDIgnoreACInputState        = 11
RAMIDMultiFunctionalRelayState = 12
RAMIDChargeState               = 13 # battery monitor function
RAMIDInverterPower1            = 14 # filtered. 16bit signed integer. Positive AC->DC. Negative DC->AC.
RAMIDInverterPower2            = 15 # ..
RAMIDOutputPower               = 16 # AC Output. 16bit signed integer.
RAMIDInverterPower1Unfiltered  = 17
RAMIDInverterPower2Unfiltered  = 18
RAMIDOutputPowerUnfiltered     = 19



WCommandSendSoftwareVersionPart0 = 0x05
WCommandSendSoftwareVersionPart1 = 0x06
WCommandGetSetDeviceState        = 0x0e
WCommandReadRAMVar               = 0x30
WCommandReadSetting              = 0x31
WCommandWriteRAMVar              = 0x32
WCommandWriteSetting             = 0x33
WCommandWriteData                = 0x34
WCommandWriteViaID               = 0x37
WSCommandReadSnapShot            = 0x38

WReplyCommandNotSupported        = 0x80
WReplyReadRAMOK                  = 0x85
WReplyReadSettingOK              = 0x86
WReplySuccesfulRAMWrite          = 0x87
WReplySuccesfulSettingWrite      = 0x88
WReplyVariableNotSupported       = 0x90
WReplySettingNotSupported        = 0x91
WReplyCommandGetSetDeviceStateOK = 0x94
WReplyAccessLevelRequired        = 0x9b

