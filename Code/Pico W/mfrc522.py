from mfrc522 import MFRC522
import utime

reader = MFRC522(
    spi_id=0,
    sck=18,
    miso=16,
    mosi=19,
    cs=20,
    rst=22
)


def get_sak(reader, raw_uid):
    # raw_uid must contain 4 UID bytes plus the BCC byte
    command = [reader.PICC_ANTICOLL1, 0x70]
    command.extend(raw_uid)
    command.extend(reader._crc(command))

    status, response, response_bits = reader._tocard(0x0C, command)

    if (
        status == reader.OK
        and response_bits == 0x18
        and len(response) >= 1
    ):
        return reader.OK, response[0]

    return reader.ERR, None


def describe_sak(sak):
    print("SAK decimal:", sak)
    print("SAK hex: 0x{:02X}".format(sak))

    if sak == 0x08:
        print("Likely card: MIFARE Classic 1K")
        print("Total memory: 1,024 bytes")
        print("Usable data blocks: 47")
        print("Approximate usable storage: 752 bytes")

    elif sak == 0x09:
        print("Likely card: MIFARE Mini")
        print("Total memory: 320 bytes")
        print("Approximate usable storage: 224 bytes")

    elif sak == 0x18:
        print("Likely card: MIFARE Classic 4K")
        print("Total memory: 4,096 bytes")
        print("Approximate usable storage: 3,440 bytes")

    elif sak == 0x00:
        print("Likely card: MIFARE Ultralight or NTAG")
        print("Exact capacity requires additional identification")

    elif sak == 0x10:
        print("Likely card: MIFARE Plus 2K")

    elif sak == 0x11:
        print("Likely card: MIFARE Plus 4K")

    elif sak == 0x20:
        print("Likely card: MIFARE DESFire or compatible card")
        print("This MicroPython driver cannot determine its capacity")

    elif sak & 0x04:
        print("UID cascade detected")
        print("This card has a longer UID")

    else:
        print("Unrecognized SAK")
        print("Exact card capacity could not be determined")


reader.init()
print("Place tag on reader...")

while True:
    status, response_bits = reader.request(reader.REQIDL)

    if status == reader.OK:
        # Unlike SelectTagSN(), anticoll() preserves the BCC byte
        status, raw_uid = reader.anticoll(reader.PICC_ANTICOLL1)

        if status == reader.OK:
            uid = raw_uid[:4]

            print("\nTag detected")
            print("UID bytes:", uid)
            print(
                "UID hex:",
                ":".join("{:02X}".format(value) for value in uid)
            )
            print(
                "CARD ID:",
                int.from_bytes(bytes(uid), "little", False)
            )

            status, sak = get_sak(reader, raw_uid)

            if status == reader.OK:
                describe_sak(sak)
            else:
                print("Failed to retrieve SAK")

            break

    utime.sleep_ms(200)