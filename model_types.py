"""Tipe model yang dipilih pengguna; tidak bergantung pada bentuk renderer EA."""
import re
from semantic_rules import BPMN_TYPES, BPMN_RELATIONS

UML_TYPES = ("Class", "Component", "Node", "Artifact", "Interface", "Actor", "Activity",
             "UseCase", "Decision", "Boundary", "Note")
ARCHIMATE_NAMES = {
    "BusinessActor": "Business Actor", "BusinessRole": "Business Role",
    "BusinessProcess": "Business Process", "BusinessService": "Business Service",
    "BusinessObject": "Business Object", "ApplicationComponent": "Application Component",
    "ApplicationService": "Application Service", "ApplicationFunction": "Application Function",
    "ApplicationInterface": "Application Interface", "DataObject": "Data Object",
    "Node": "Node", "Device": "Device", "SystemSoftware": "System Software",
    "CommunicationNetwork": "Communication Network", "TechnologyService": "Technology Service",
    "Artifact": "Artifact", "Capability": "Capability", "Goal": "Goal",
    "Requirement": "Requirement", "WorkPackage": "Work Package",
}


def archimate(name):
    return "ArchiMate3::ArchiMate_" + name


EA_TYPE_LABELS = {name: name for name in UML_TYPES}
EA_TYPE_LABELS.update({archimate(name): "ArchiMate: " + label for name, label in ARCHIMATE_NAMES.items()})
EA_TYPE_LABELS.update({value: 'BPMN: '+value.split('::')[1] for value in BPMN_TYPES.values()})
EA_ELEMENT_TYPES = tuple(EA_TYPE_LABELS)
EA_LABEL_TYPES = {label: name for name, label in EA_TYPE_LABELS.items()}

# (EA connector base type, qualified stereotype). Semantic relationships are
# selected explicitly; arrow appearance alone cannot distinguish Access/Serving.
RELATION_TYPES = {
    "Dependency": ("Dependency", ""), "Association": ("Association", ""),
    "Realisation": ("Realisation", ""), "Generalization": ("Generalization", ""),
    "ArchiMate: Association": ("Association", archimate("Association")),
    "ArchiMate: Serving": ("Dependency", archimate("Serving")),
    "ArchiMate: Access": ("Dependency", archimate("Access")),
    "ArchiMate: Realization": ("Realisation", archimate("Realization")),
    "ArchiMate: Flow": ("Dependency", archimate("Flow")),
    "ArchiMate: Triggering": ("Dependency", archimate("Triggering")),
    "ArchiMate: Assignment": ("Association", archimate("Assignment")),
}
RELATION_TYPES.update(BPMN_RELATIONS)


def default_relation_type(src_type, tgt_type, directed, profile):
    if profile == "archimate":
        if src_type in (archimate("BusinessActor"), archimate("BusinessRole")) and tgt_type == archimate("BusinessProcess"):
            return "ArchiMate: Assignment"
        return "ArchiMate: Association"
    return "Association" if "Actor" in (src_type, tgt_type) or not directed else "Dependency"


def infer_archimate(item, default_type):
    """Usulan tipe, beserta asalnya, untuk diperiksa pengguna sebelum import."""
    style = re.sub(r"[^a-z]", "", item.get("source_style", "").lower())
    # Shapes from the draw.io ArchiMate library often carry semantic names.
    for name in sorted(ARCHIMATE_NAMES, key=len, reverse=True):
        if name.lower() in style:
            return archimate(name), "bentuk sumber"
    source_words = set(re.findall(r"[a-z]+", item.get("source_style", "").lower()))
    for keys, name in [({"server"}, "Node"), ({"network", "jaringan"}, "CommunicationNetwork")]:
        if source_words & keys:
            return archimate(name), "bentuk sumber"
    text = re.sub(r"[^a-z0-9]+", " ", item["text"].lower()).strip()
    words = set(text.split())
    for phrase, name in [
        ("business service", "BusinessService"), ("business process", "BusinessProcess"),
        ("application service", "ApplicationService"), ("application component", "ApplicationComponent"),
        ("data object", "DataObject"), ("system software", "SystemSoftware"),
        ("technology service", "TechnologyService"), ("business actor", "BusinessActor"),
    ]:
        if phrase in text:
            return archimate(name), "nama elemen (periksa)"
    for keys, name in [({"server", "node"}, "Node"), ({"network", "jaringan"}, "CommunicationNetwork"),
                       ({"device", "perangkat"}, "Device")]:
        if words & keys:
            return archimate(name), "nama elemen (periksa)"
    for context in item.get("context", []):
        layer = set(re.findall(r"[a-z]+", context.lower()))
        for keys, name in [({"data"}, "DataObject"), ({"application", "aplikasi"}, "ApplicationComponent"),
                           ({"business", "bisnis"}, "BusinessService"),
                           ({"technology", "teknologi"}, "TechnologyService")]:
            if layer & keys:
                return archimate(name), "lapisan sumber (periksa)"
    return default_type, "default"
