

F_REQUEST = {
    "DC": 0,
    "AC_L1": 1,
    "AC_L2": 2,
    "AC_L3": 3,
    "AC_L4": 4,
    "MasterMultiLED": 5,
    "Snapshot": 6,
    "Reset_VEBus_devices": 8,
    "Send_BOL": 9,
}

PHASE_INFO = {
    'L4' : 0x05,
    'L3' : 0x06,
    'L2' : 0x07,
    'L1_1ph' : 0x08,
    'L1_2ph' : 0x09,
    'L1_3ph' : 0x0A,
    'L1_4ph' : 0x0B,
    'DC' : 0x0C,
}

PHASE_INFO_invers = {v: k for k, v in PHASE_INFO.items()}

MULTI_STATE_invers = {
    0x0 : 'Down',
    0x1 : 'Startup',
    0x2 : 'Off',
    0x3 : 'Slave',
    0x4 : 'InvertFull',
    0x5 : 'InvertHalf',
    0x6 : 'InvertAES',
    0x7 : 'PowerAssist',
    0x8 : 'Bypass',
    0x9 : 'StateCharge',
}


RAM_IDS = {
    "UMainsRMS": 0,
    "IMainsRMS": 1,
    "UInverterRMS": 2,
    "IInverterRMS": 3,
    "UBat": 4,
    "IBat": 5,
    "UBatRMS": 6,  # RMS=value of ripple voltage
    "InverterPeriodTime": 7,  # time-base 0.1s
    "MainsPeriodTime": 8,  # time-base 0.1s
    "SignedACLoadCurrent": 9,
    "VirtualSwitchPosition": 10,
    "IgnoreACInputState": 11,
    "MultiFunctionalRelayState": 12,
    "ChargeState": 13,  # battery monitor function
    "InverterPower1": 14,  # filtered. 16bit signed integer. Positive AC->DC. Negative DC->AC.
    "InverterPower2": 15,  # ..
    "OutputPower": 16,  # AC Output. 16bit signed integer.
    "InverterPower1Unfiltered": 17,
    "InverterPower2Unfiltered": 18,
    "OutputPowerUnfiltered": 19,
}

RAM_IDS_scale = {
    "UMainsRMS": lambda x: x * 0.01,
    "IMainsRMS": lambda x: x * 0.01,
    "UInverterRMS": lambda x: x * 0.01,
    "IInverterRMS": lambda x: x * 0.01,
    "UBat": lambda x: x * 0.01,
    "IBat": lambda x: x * 0.01,
    "UBatRMS": lambda x: x * 0.01,
    "InverterPeriodTime": lambda x: (x+256) * 0.0000510,
    "MainsPeriodTime": lambda x: 1/ (x * 0.0001024),
    "SignedACLoadCurrent": lambda x: x * 0.01,
    "VirtualSwitchPosition": lambda x: x & 0x8,
    "IgnoreACInputState":  lambda x: x & 0x01,
    "MultiFunctionalRelayState": lambda x: x & 0x20,
    "ChargeState": lambda x: x * 0.5,
    "InverterPower1": lambda x: x,
    "InverterPower2": lambda x: x,
    "OutputPower": lambda x: x,
    "InverterPower1Unfiltered": lambda x: x,
    "InverterPower2Unfiltered": lambda x: x,
    "OutputPowerUnfiltered": lambda x: x,
}


RAM_IDS_write= {
    "ChargeState": lambda x: x * 2,
}



RAM_IDS_invers = {v: k for k, v in RAM_IDS.items()}


WCommandSendSoftwareVersionPart0 = 0x05
WCommandSendSoftwareVersionPart1 = 0x06
WCommandGetSetDeviceState        = 0x0e
WCommandReadRAMVar               = 0x30
WCommandReadSetting              = 0x31
WCommandWriteRAMVar              = 0x32
WCommandWriteSetting             = 0x33
WCommandWriteData                = 0x34
WCommandGetSettingInfo           = 0x35
WCommandGetRAMVarInfo            = 0x36

WCommandWriteViaID               = 0x37
WSCommandReadSnapShot            = 0x38

WReplyCommandNotSupported        = 0x80
WReplyReadRAMOK                  = 0x85
WReplyReadSettingOK              = 0x86
WReplySuccesfulRAMWrite          = 0x87
WReplySuccesfulSettingWrite      = 0x88
WReplySuccesfulRAMVarInfo        = 0x8E
WReplyVariableNotSupported       = 0x90
WReplySettingNotSupported        = 0x91
WReplyCommandGetSetDeviceStateOK = 0x94
WReplyAccessLevelRequired        = 0x9b

