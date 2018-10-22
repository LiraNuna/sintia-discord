from configparser import ConfigParser

from sintia.sintia import Sintia


if __name__ == '__main__':
    config = ConfigParser()
    config.read('config.ini')

    sintia = Sintia(config)
    sintia.run()
