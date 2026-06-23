def classFactory(iface):
    from .main import AddressMatcherPlugin
    return AddressMatcherPlugin(iface)
