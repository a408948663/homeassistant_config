'''
版本：v0.01
1.适用于网关lumi.gateway.v3，空调伴侣lumi.acpartner.v3；
2.用于将空调伴侣的插件开关、警戒开关和网关的警戒开关接入HA;
3.官方的xiaomi_miio中的switch组件是含有对空调伴侣lumi.acpartner.v3的插件开关的接入,
    为免得插座用官方，警戒用自制的麻烦。我将插座的功能也抄过来了；


使用说明：
1.适用于HA0.88之后的版本，之前的版本需修改文件名和所在目录名；
2.只在lumi.gateway.v3、lumi.acpartner.v3两款网关上测试过；
3.配置文件里添加：
switch:
  - platform: mi_ac_partner
    name: (可选)
    host: （必填）
    token: （必填）

4.将本文件switch.py放到：../custom_components/mi_ac_partner/目录下。
5.重启Home Assistant。

von(vaughan.zeng@gmail.com)
'''
import asyncio
from functools import partial
import logging

import voluptuous as vol
from homeassistant.components.switch import (
    DOMAIN, PLATFORM_SCHEMA, SwitchDevice)
from homeassistant.const import (
    ATTR_ENTITY_ID, CONF_HOST, CONF_NAME, CONF_TOKEN)
from homeassistant.exceptions import PlatformNotReady
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DATA_KEY = 'switch.xiaomi_miio'
CONF_MODEL = 'model'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_HOST): cv.string,
    vol.Required(CONF_TOKEN): vol.All(cv.string, vol.Length(min=32, max=32)),
    vol.Optional(CONF_NAME): cv.string,
    vol.Optional(CONF_MODEL): vol.In(
        ['lumi.acpartner.v3',
         'lumi.gateway.v3',
         ]),
})

ATTR_LOAD_POWER = 'load_power'
ATTR_MODEL = 'model'
SUCCESS = ['ok']

FEATURE_FLAGS_GENERIC = 0


async def async_setup_platform(hass, config, async_add_entities,
                               discovery_info=None):
    """Set up the switch from config."""
    from miio import Device, DeviceException
    if DATA_KEY not in hass.data:
        hass.data[DATA_KEY] = {}

    host = config.get(CONF_HOST)
    name = config.get(CONF_NAME)
    token = config.get(CONF_TOKEN)
    model = config.get(CONF_MODEL)

    _LOGGER.info("开关初始化：host：%s (token：%s...)", host, token[:5])

    devices = []
    unique_id = None

    if model is None:
        try:
            miio_device = Device(host, token)
            device_info = miio_device.info()
            model = device_info.model
            unique_id = "{}-{}".format(model, device_info.mac_address)
            _LOGGER.info("%s %s %s detected",
                         model,
                         device_info.firmware_version,
                         device_info.hardware_version)
        except DeviceException:
            raise PlatformNotReady

    if name == None:
        if model == 'lumi.gateway.v3':
            name = 'Xiaomi Gateway ' + host.split('.')[3]
        elif model == 'lumi.acpartner.v3':
            name = 'Xiaomi AC Partner ' + host.split('.')[3]

    if model in ['lumi.gateway.v3']:
        from miio import Device
        switch = Device(host, token)
        device = GatewayAlarm(name, switch, model, unique_id)
        devices.append(device)
        hass.data[DATA_KEY][host] = device
    elif model in ['lumi.acpartner.v3']:
        from miio import AirConditioningCompanionV3
        switch = AirConditioningCompanionV3(host, token)
        for plug_switch in [True, False]:
            device = XiaomiAirConditioningCompanionSwitch(name, switch, model,
                                                      unique_id, plug_switch)
            devices.append(device)
            hass.data[DATA_KEY][host] = device
    else:
        _LOGGER.error(
            'Unsupported device found! Please create an issue at '
            'https://github.com/rytilahti/python-miio/issues '
            'and provide the following data: %s', model)
        return False

    async_add_entities(devices, update_before_add=True)


class GatewayAlarm(SwitchDevice):

    def __init__(self, name, switch, model, unique_id):
        self._name = name + ' alarm'
        self._switch = switch
        self._model = model
        self._unique_id = unique_id
        self._icon = 'mdi:alarm-light'
        self._availabe = False
        self._state = None
        self._state_attrs = {
            ATTR_MODEL: self._model,
        }
        self._device_features = FEATURE_FLAGS_GENERIC
        self._skip_update = False

    @property
    def should_poll(self):
        """Poll the plug."""
        return True

    @property
    def unique_id(self):
        """Return an unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the device if any."""
        return self._name

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._icon

    @property
    def available(self):
        """Return true when state is known."""
        return self._available

    @property
    def device_state_attributes(self):
        """Return the state attributes of the device."""
        return self._state_attrs

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._state

    async def _try_command(self, mask_error, func, *args, **kwargs):
        """Call a plug command handling error messages."""
        from miio import DeviceException
        try:
            result = await self.hass.async_add_executor_job(
                partial(func, *args, **kwargs))
            _LOGGER.debug("Response received from plug: %s", result)
            return result == SUCCESS
        except DeviceException as exc:
            _LOGGER.error(mask_error, exc)
            self._available = False
            return False

    def alarm_on(self):
        return self._switch.send('set_arming',['on'])

    def alarm_off(self):
        return self._switch.send('set_arming',['off'])

    async def _try_command_alarm(self, mask_error, func, *args, **kwargs):
        """Call a plug command handling error messages."""
        from miio import DeviceException
        try:
            if func == 'on':
                result =  await self.hass.async_add_executor_job(
                    partial(self.alarm_on, *args, **kwargs))
            if func == 'off':
                result =  await self.hass.async_add_executor_job(
                    partial(self.alarm_off, *args, **kwargs))

            _LOGGER.info("Response received from acpartner alarm: %s", result)
            return result == SUCCESS
        except DeviceException as exc:
            _LOGGER.error(mask_error, exc)
            self._available = False
            return False

    async def async_turn_on(self, **kwargs):
        """Turn the plug on."""
        result = await self._try_command_alarm(
            "Turning the Alarm failed.", 'on')
        if result:
            self._state = True
            self._skip_update = True

    async def async_turn_off(self, **kwargs):
        """Turn the plug off."""
        result = await self._try_command_alarm(
            "Turning the Alarm failed.", 'off')
        if result:
            self._state = False
            self._skip_update = True

    def alarm_status(self):
        return self._switch.send("get_arming",[])[0]

    async def async_update(self):
        """Fetch state from the device."""
        from miio import DeviceException

        # On state change the device doesn't provide the new state immediately.
        if self._skip_update:
            self._skip_update = False
            return
        try:
            state = await self.hass.async_add_executor_job(self.alarm_status)
            _LOGGER.debug("Got new state: %s", state)
            self._available = True
            self._state = state == 'on'
        except DeviceException as ex:
            self._available = False
            _LOGGER.error("Got exception while fetching the state: %s", ex)


class XiaomiAirConditioningCompanionSwitch(GatewayAlarm):
    """Representation of a Xiaomi AirConditioning Companion."""
    def __init__(self, name, switch, model, unique_id, plug_switch):
        """Initialize the acpartner switch."""
        if unique_id is not None and plug_switch:
            unique_id = "{}-{}".format(unique_id, 'plug')

        super().__init__(name, switch, model, unique_id)
        if plug_switch:
            self._name = name + ' plug'
            self._icon = 'mdi:power-socket-au'
        self._plug_switch = plug_switch
        self._state_attrs.update({
            ATTR_LOAD_POWER: None,
        })

    async def async_turn_on(self, **kwargs):
        """Turn the socket on."""
        if self._plug_switch:
            result = await self._try_command(
                "Turning the socket on failed.", self._switch.socket_on)
        else:
            result = await self._try_command_alarm(
                "Turning the Alarm failed.", 'on')
        if result:
            self._state = True
            self._skip_update = True

    async def async_turn_off(self, **kwargs):
        """Turn the socket off."""
        if self._plug_switch:
            result = await self._try_command(
                "Turning the socket off failed.", self._switch.socket_off)
        else:
            result = await self._try_command_alarm(
                "Turning the Alarm failed.", 'off')
        if result:
            self._state = False
            self._skip_update = True

    async def async_update(self):
        """Fetch state from the device."""
        from miio import DeviceException
        # On state change the device doesn't provide the new state immediately.
        if self._skip_update:
            self._skip_update = False
            return
        try:
            self._available = True
            if self._plug_switch:
                state = await self.hass.async_add_executor_job(self._switch.status)
                _LOGGER.debug("Got new state: %s", state)
                self._state = state.power_socket == 'on'
                self._state_attrs[ATTR_LOAD_POWER] = state.load_power
            else:
                state = await self.hass.async_add_executor_job(self.alarm_status)
                self._state = state == 'on'
        except DeviceException as ex:
            self._available = False
            _LOGGER.error("Got exception while fetching the state: %s", ex)

