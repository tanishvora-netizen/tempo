"""Fictional names for the synthetic dataset. None of these are meant to be real companies.

All email domains use the reserved `.example` top-level domain (RFC 2606).
"""

COMPANY_NAME = "Kestrel Ridge Manufacturing, Inc."
COMPANY_DOMAIN = "kestrelridge.example"

# (name, category, sells_goods)
VENDORS: tuple[tuple[str, str, bool], ...] = (
    ("Tamarack Steel Supply", "raw_materials", True),
    ("Gullwing Freight Lines", "freight", False),
    ("Inkberry Packaging Co.", "packaging", True),
    ("Basalt Fastener Works", "components", True),
    ("Cobalt Creek Industrial Gases", "raw_materials", True),
    ("Driftwood Pallet & Crate", "packaging", True),
    ("Fernhill Electric Supply", "components", True),
    ("Harborline Logistics", "freight", False),
    ("Ironwood Machining", "components", True),
    ("Juniper Polymer Resins", "raw_materials", True),
    ("Keelhaven Staffing", "services", False),
    ("Lanternfish Software", "software", False),
    ("Meridian Row Calibration Labs", "services", False),
    ("Northgate Abrasives", "components", True),
    ("Oakmont Facility Services", "services", False),
    ("Quarry Lane Aggregates", "raw_materials", True),
    ("Redfield Hydraulics", "components", True),
    ("Saltmarsh Coatings", "raw_materials", True),
    ("Tidewater Bearing Supply", "components", True),
    ("Upland Safety Gear", "supplies", True),
    ("Vireo Office Supply", "supplies", True),
    ("Westbrook Tool & Die", "components", True),
    ("Yarrow Maintenance Group", "services", False),
    ("Zephyr Point Utilities Brokerage", "utilities", False),
    ("Bramblewood Chemicals", "raw_materials", True),
    ("Cinderhill Foundry", "raw_materials", True),
    ("Dunmore Conveyor Systems", "components", True),
    ("Elmstead Waste Hauling", "services", False),
    ("Foxglove Lab Supplies", "supplies", True),
    ("Hollisford Valve Co.", "components", True),
    ("Jasper Mill Textiles", "raw_materials", True),
    ("Kettle Rock Compressors", "components", True),
    ("Larchmere IT Services", "software", False),
    ("Millrace Engineering Consultants", "services", False),
    ("Nettlefield Wire & Cable", "components", True),
    ("Ospreyline Courier", "freight", False),
    ("Pinegrove Lubricants", "supplies", True),
    ("Rookwood Signage", "services", False),
    ("Sorrel Bay Plastics", "raw_materials", True),
    ("Thistledown Uniform Rental", "services", False),
)

CUSTOMERS: tuple[str, ...] = (
    "Bluefin Marine Outfitters",
    "Copperline Rail Systems",
    "Greywater Agricultural Equipment",
    "Halcyon Medical Devices",
    "Ridgeback Construction Supply",
    "Starling Aerospace Components",
    "Tallgrass Energy Services",
    "Wrenfield HVAC Distributors",
    "Ashgrove Furniture Makers",
    "Brightwater Pump & Filter",
    "Caldera Mining Supply",
    "Dovetail Cabinetry",
    "Everly Food Equipment",
    "Fairhaven Boatworks",
    "Glenmoor Automation",
    "Heronsgate Packaging Lines",
    "Islemark Robotics",
    "Kingfisher Water Systems",
    "Larkhill Trailer Co.",
    "Moorcroft Elevator Service",
    "Northfield Dairy Equipment",
    "Pembrook Solar Racking",
    "Quillon Defense Fabrication",
    "Rosebay Brewing Systems",
    "Silverbirch Medical Carts",
)

LINE_ITEMS: dict[str, tuple[str, ...]] = {
    "raw_materials": ("Cold-rolled sheet, 14 ga", "Bar stock, 1018 steel", "Resin pellets, 25 kg bag", "Argon cylinder refill", "Coating concentrate, 5 gal"),
    "components": ("Hex bolt M10 x 40, box of 100", "Ball bearing 6204-2RS", "Hydraulic fitting kit", "Control relay 24V", "CNC-machined bracket"),
    "packaging": ("Corrugated carton 24x18x12", "Stretch wrap, 18 in roll", "Heat-treated pallet 48x40", "Foam insert set"),
    "freight": ("LTL freight, inbound", "Full truckload, Memphis lane", "Expedited freight surcharge", "Liftgate delivery"),
    "services": ("Technician labor, hours", "Calibration service, per instrument", "Temporary staffing, hours", "Engineering review, hours"),
    "software": ("Platform subscription, monthly", "Additional user seats", "Support plan, monthly"),
    "supplies": ("Nitrile gloves, case", "Safety glasses, box of 12", "Copy paper, case", "Shop towels, bale"),
    "utilities": ("Electricity supply, monthly", "Natural gas supply, monthly"),
}

STREETS: tuple[str, ...] = (
    "1180 Commerce Pkwy",
    "42 Foundry Rd",
    "7700 Industrial Blvd",
    "315 Harbor Way",
    "96 Millbrook Ln",
    "2201 Gateway Dr",
    "18 Quarry St",
    "640 Riverside Ave",
)

CITIES: tuple[str, ...] = (
    "Dayton, OH 45402",
    "Fort Wayne, IN 46802",
    "Rockford, IL 61101",
    "Erie, PA 16501",
    "Kalamazoo, MI 49007",
    "Peoria, IL 61602",
    "Akron, OH 44308",
    "Lansing, MI 48933",
)
