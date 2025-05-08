DOMAIN = "bentel_absoluta"
DEFAULT_PORT = 3064
DEFAULT_TIMEOUT = 5
PROTOCOL_VERSION = 2
# Framing bytes
FRAME_START = 0x7E
FRAME_END = 0x7F
ESCAPE = 0x7D
# CRC16-CCITT parameters
CRC_POLY = 0x1021
CRC_INIT = 0xFFFF
CRC_XOROUT = 0x0000
CMD_OPEN_SESSION = 0x0100  # Sostituisci con il valore corretto del comando
DEFAULT_TIMEOUT = 5  # Imposta il timeout predefinito in secondi
CMD_PARTITION_ARM = 0x0801  # Comando per armare la partizione
CMD_PARTITION_DISARM = 0x0802  # Comando per disarmare la partizione
CMD_OUTPUT_CTRL = 0x0902  # Comando per controllare le uscite
