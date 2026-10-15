"""Small synthetic Visio package for decoder tests; no company documents."""
import io
import zipfile

V = "http://schemas.microsoft.com/office/visio/2012/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


def make_vsdx(master_symbol=False):
    metadata = f'''<Pages xmlns="{V}" xmlns:r="{R}">
      <Page ID="0" Name="Applications"><PageSheet><Cell N="PageHeight" V="10"/></PageSheet><Rel r:id="r1"/></Page>
      <Page ID="1" Name="Second"><PageSheet><Cell N="PageHeight" V="10"/></PageSheet><Rel r:id="r2"/></Page>
      <Page ID="2" Name="Background" Background="1"><Rel r:id="r2"/></Page>
    </Pages>'''
    rels = f'''<Relationships xmlns="{P}">
      <Relationship Id="r1" Target="page1.xml"/>
      <Relationship Id="r2" Target="page2.xml"/>
    </Relationships>'''
    symbol = ('''<Shape ID="2" Master="1" Type="Group"><Cell N="PinX" V="2"/><Cell N="PinY" V="6"/>
      <Shapes><Shape ID="20"><Cell N="Width" V="1"/><Cell N="Height" V="0.5"/>
      <Cell N="PinX" V="0.5"/><Cell N="PinY" V="0.5"/><Text>CRM</Text></Shape></Shapes></Shape>'''
      if master_symbol else '''<Shape ID="2" NameU="Process"><Cell N="PinX" V="2"/>
      <Cell N="PinY" V="6"/><Cell N="Width" V="1.5"/><Cell N="Height" V="0.8"/><Text>CRM</Text></Shape>''')
    source_id = "20" if master_symbol else "2"
    page = f'''<PageContents xmlns="{V}"><Shapes>
      <Shape ID="1" NameU="Application Container"><Cell N="PinX" V="4"/><Cell N="PinY" V="5"/>
        <Cell N="Width" V="8"/><Cell N="Height" V="5"/><Text>Application</Text></Shape>
      {symbol}
      <Shape ID="3" NameU="Process"><Cell N="PinX" V="6"/><Cell N="PinY" V="6"/>
        <Cell N="Width" V="1.5"/><Cell N="Height" V="0.8"/><Text>ERP</Text></Shape>
      <Shape ID="4" NameU="Dynamic connector"><Cell N="BeginX" V="2"/><Cell N="BeginY" V="6"/>
        <Cell N="EndX" V="6"/><Cell N="EndY" V="6"/><Cell N="EndArrow" V="13"/><Text>sync</Text></Shape>
      <Shape ID="5" NameU="Text"><Cell N="PinX" V="4"/><Cell N="PinY" V="9"/>
        <Cell N="Width" V="3"/><Cell N="Height" V="0.5"/><Text>Example</Text></Shape>
    </Shapes><Connects>
      <Connect FromSheet="4" FromCell="BeginX" ToSheet="{source_id}"/>
      <Connect FromSheet="4" FromCell="EndX" ToSheet="3"/>
    </Connects></PageContents>'''
    parts = {"visio/pages/pages.xml": metadata,
             "visio/pages/_rels/pages.xml.rels": rels,
             "visio/pages/page1.xml": page, "visio/pages/page2.xml": page}
    if master_symbol:
        parts.update({
            "visio/masters/masters.xml": f'<Masters xmlns="{V}" xmlns:r="{R}"><Master ID="1" NameU="Server"><Rel r:id="m1"/></Master></Masters>',
            "visio/masters/_rels/masters.xml.rels": f'<Relationships xmlns="{P}"><Relationship Id="m1" Target="master1.xml"/></Relationships>',
            "visio/masters/master1.xml": f'<MasterContents xmlns="{V}"><Shapes><Shape ID="0"><Cell N="Width" V="1.5"/><Cell N="Height" V="0.8"/></Shape></Shapes></MasterContents>',
        })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)
    return buf.getvalue()
