#!
# -*- coding: utf-8 -*-

'''
╔════════════════════════════════════════════════════════════════════════════════════╗
║                                                                                    ║
║   Copyright (c) 2018 Yorik van Havre                                               ║
║   Copyright (c) 2023 https://prrvchr.github.io                                     ║
║                                                                                    ║
║   Permission is hereby granted, free of charge, to any person obtaining            ║
║   a copy of this software and associated documentation files (the "Software"),     ║
║   to deal in the Software without restriction, including without limitation        ║
║   the rights to use, copy, modify, merge, publish, distribute, sublicense,         ║
║   and/or sell copies of the Software, and to permit persons to whom the Software   ║
║   is furnished to do so, subject to the following conditions:                      ║
║                                                                                    ║
║   The above copyright notice and this permission notice shall be included in       ║
║   all copies or substantial portions of the Software.                              ║
║                                                                                    ║
║   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,                  ║
║   EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES                  ║
║   OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.        ║
║   IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY             ║
║   CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,             ║
║   TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE       ║
║   OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.                                    ║
║                                                                                    ║
╚════════════════════════════════════════════════════════════════════════════════════╝
'''

from bpy_extras.node_shader_utils import PrincipledBSDFWrapper
from rna_prop_ui import PropertyPanel

from bpy import types
import mathutils

import sys, bpy, xml.sax, zipfile, os, json

bl_info = {
    'name': 'FreeCAD-Importer',
    'category': 'Import-Export',
    'author': 'prrvchr',
    'version': (0, 0, 1),
    'blender': (3, 0, 1),
    'location': 'File > Import > FreeCAD',
    'description': 'Imports files from FreeCAD. Only Part and Mesh objects are supported.'}

class FreeCADGUI_xml_handler(xml.sax.ContentHandler):

    """A XML handler to process the FreeCAD GUI xml data"""

    # this creates a dictionary where each key is a FC object Name,
    # and each value is object Visibility

    def __init__(self):

        self.guidata = {}
        self._current = None
        self._currentprop = False
        self._currentval = None

    # Call when an element starts
    def startElement(self, tag, attrs):

        if tag == 'ViewProvider':
            self._current = attrs['name']
        elif tag == 'Property' and attrs['name'] == 'Visibility':
            self._currentprop = True
        elif tag == 'Bool' and self._currentprop:
            if attrs['value'] == 'true':
                self._currentval = True
            else:
                self._currentval = False

    # Call when an elements ends
    def endElement(self, tag):

        if tag == 'ViewProvider':
            if self._current and self._currentval is not None:
                self.guidata[self._current] = self._currentval
                self._current = None
                self._currentval = None
        elif tag == 'Property':
            if self._currentprop:
                self._currentprop = False


def import_fcstd(path,
                 filename='',
                 skiphidden=True,
                 placement=True,
                 allmaterial=True,
                 aspolygons=True,
                 tessellation=1.0,
                 scale=0.001,
                 newcollection=False,
                 report=None):

    """Reads a FreeCAD .FCStd file and creates Blender objects"""
    print("import_fcstd() 1")
    try:
        from . import FreeCAD
    except:
        print("Unable to import the FreeCAD Python module. Make sure it is installed on your system")
        print("and compiled with Python3 (same version as Blender).")
        if report:
            report({'ERROR'}, 'Unable to import the FreeCAD Python module. Check you have same Python version for FreeCAD and Blender.')
        return {'CANCELLED'}
    root = 'Blender'
    # check if we have a GUI document
    print("import_fcstd() 2")
    guidata = {}
    zdoc = zipfile.ZipFile(path + filename)
    if zdoc:
        if 'GuiDocument.xml' in zdoc.namelist():
            gf = zdoc.open('GuiDocument.xml')
            data = gf.read()
            gf.close()
            Handler = FreeCADGUI_xml_handler()
            xml.sax.parseString(data, Handler)
            guidata = Handler.guidata
        zdoc.close()
        #print ("Filename", path + filename, "guidata:", guidata)
    doc = FreeCAD.open(path + filename)
    docname = doc.Name
    if not doc:
        print("Unable to open the given FreeCAD file")
        if report:
            report({'ERROR'}, 'Unable to open the given FreeCAD file')
        return {'CANCELLED'}
    print ("Transferring", len(doc.Objects), "objects to Blender")

    # import some FreeCAD modules needed below. After "import FreeCAD" these modules become available
    import Part

    def hascurves(shape):
        for e in shape.Edges:
            if not isinstance(e.Curve, (Part.Line, Part.LineSegment)):
                return True
        return False

    name, sep, ext = filename.rpartition('.')
    if newcollection:
        print("Create new collection 1")
        bcoll = _getNewCollection(bpy, name)
    else:
        print("Use collection 1")
        bcoll = bpy.data.collections.get(name)
    if bcoll is None:
        print("Create new collection 2")
        bcoll = _getNewCollection(bpy, name)
        newcollection = True

    # create materials
    i = 0
    if allmaterial:
        for obj in doc.Objects:
            print("Create material 1 %s" % obj.Label)
            if obj.isDerivedFrom('App::MaterialObject'):
                print("Create material 2 %s" % obj.Label)
                bmat = bpy.data.materials.get(obj.Label)
                if bmat is None:
                    print("Create material 3 %s" % obj.Label)
                    bmat = bpy.data.materials.new(name=obj.Label)
                    bmat.use_nodes = True
                    bmat.node_tree.nodes.clear()
                    _setMaterialNodes(bmat, obj, root)
                    i += 1
    print("Create material Total: %s" % i)

    # for a cleaning mesh naming we need to clean orphan mesh
    for bmesh in bpy.data.meshes:
        if bmesh.users == 0:
            bpy.data.meshes.remove(bmesh)

    for obj in doc.Objects:
        print("Importing:", obj.Label)
        if skiphidden:
            if obj.Name in guidata and not guidata[obj.Name]:
                print(obj.Name, "is invisible. Skipping.")
                continue

        verts = []
        edges = []
        faces = []
        faceedges = [] # a placeholder to store edges that belong to a face

        if obj.isDerivedFrom('Part::Feature'):
            # create mesh from shape
            print("Create mesh from shape:", obj.Label)
            shape = obj.Shape
            if placement:
                placement = obj.Placement
                shape = obj.Shape.copy()
                shape.Placement = placement.inverse().multiply(shape.Placement)
            if shape.Faces:
                if aspolygons:
                    # write FreeCAD faces as polygons when possible
                    for face in shape.Faces:
                        if (len(face.Wires) > 1) or (not isinstance(face.Surface,Part.Plane)) or hascurves(face):
                            # face has holes or is curved, so we need to triangulate it
                            rawdata = face.tessellate(tessellation)
                            for v in rawdata[0]:
                                vl = [v.x,v.y,v.z]
                                if not vl in verts:
                                    verts.append(vl)
                            for f in rawdata[1]:
                                nf = []
                                for vi in f:
                                    nv = rawdata[0][vi]
                                    nf.append(verts.index([nv.x,nv.y,nv.z]))
                                faces.append(nf)
                        else:
                            f = []
                            ov = face.OuterWire.OrderedVertexes
                            for v in ov:
                                vl = [v.X,v.Y,v.Z]
                                if not vl in verts:
                                    verts.append(vl)
                                f.append(verts.index(vl))
                            # FreeCAD doesn't care about verts order. Make sure our loop goes clockwise
                            c = face.CenterOfMass
                            v1 = ov[0].Point.sub(c)
                            v2 = ov[1].Point.sub(c)
                            n = face.normalAt(0,0)
                            if (v1.cross(v2)).getAngle(n) > 1.57:
                                f.reverse() # inverting verts order if the direction is couterclockwise
                            faces.append(f)
                        for e in face.Edges:
                            faceedges.append(e.hashCode())
                else:
                    # triangulate and make faces
                    rawdata = shape.tessellate(tessellation)
                    for v in rawdata[0]:
                        verts.append([v.x,v.y,v.z])
                    for f in rawdata[1]:
                        faces.append(f)
                    for face in shape.Faces:
                        for e in face.Edges:
                            faceedges.append(e.hashCode())

            for edge in shape.Edges:
                # Treat remaining edges (that are not in faces)
                if not (edge.hashCode() in faceedges):
                    if hascurves(edge):
                        dv = edge.discretize(9) #TODO use tessellation value
                        for i in range(len(dv)-1):
                            dv1 = [dv[i].x,dv[i].y,dv[i].z]
                            dv2 = [dv[i+1].x,dv[i+1].y,dv[i+1].z]
                            if not dv1 in verts:
                                verts.append(dv1)
                            if not dv2 in verts:
                                verts.append(dv2)
                            edges.append([verts.index(dv1),verts.index(dv2)])
                    else:
                        e = []
                        for vert in edge.Vertexes:
                            # TODO discretize non-linear edges
                            v = [vert.X,vert.Y,vert.Z]
                            if not v in verts:
                                verts.append(v)
                            e.append(verts.index(v))
                        edges.append(e)

        elif obj.isDerivedFrom('Mesh::Feature'):
            # convert freecad mesh to blender mesh
            print("Convert freecad mesh to blender mesh:", obj.Label)
            mesh = obj.Mesh
            if placement:
                placement = obj.Placement
                mesh = obj.Mesh.copy() # in meshes, this zeroes the placement
            t = mesh.Topology
            verts = [[v.x,v.y,v.z] for v in t[0]]
            faces = t[1]

        else:
            print("Can't convert FreeCAD object:", obj.Label)

        if verts and (faces or edges):
            # create or update object with mesh and material data
            bobj = None
            bmat = None
            if not newcollection:
                # locate existing object in the collection (object with same name)
                bobj = bcoll.objects.get(obj.Label)
            if bobj:
                print("update object: %s" % obj.Label)
                # update only the mesh of existing object.
                bobj.data.clear_geometry()
                bobj.data.from_pydata(verts, edges, faces)
            else:
                # create new object
                print("create new object: %s" % obj.Label)
                bmesh = bpy.data.meshes.new(name=obj.Label)
                bmesh.from_pydata(verts, edges, faces)
                bmesh.update()
                bobj = bpy.data.objects.new(obj.Label, bmesh)
                bcoll.objects.link(bobj)
                # if we want to be able to go back to FreeCAD, we need to keep the Label
                bobj['Name'] = obj.Name
                bobj['Label2'] = obj.getPropertyByName('Label2')
            if placement:
                bobj.location = placement.Base.multiply(scale)
                m = bobj.rotation_mode
                bobj.rotation_mode = 'QUATERNION'
                if placement.Rotation.Angle:
                    # FreeCAD Quaternion is XYZW while Blender is WXYZ
                    q = (placement.Rotation.Q[3], ) + placement.Rotation.Q[:3]
                    bobj.rotation_quaternion = (q)
                    bobj.rotation_mode = m
                bobj.scale = (scale,scale,scale)
            print("Import material 1")
            print("Import material 2 PropertyList: %s" % (obj.PropertiesList, ))
            if 'Material' in obj.PropertiesList:
                print("Import material 3")
                mat = obj.Material
                # if we have material we need to add only if it doesn't exist
                if mat and bobj.data.materials.get(mat.Label) is None:
                    bmat = bpy.data.materials.get(mat.Label)
                    if bmat is not None:
                        print("Import material done: %s" % mat.Label)
                        bobj.data.materials.append(bmat)

    FreeCAD.closeDocument(docname)

    print("Import finished without errors")
    return {'FINISHED'}


def _setMaterialNodes(bmat, mat, root):
    links = {}
    sockets = {}
    inputs = {}
    outputs = {}
    data = mat.Material.get(root)
    print("_setMaterialNodes() 1 data: %s" % data)
    if data:
        nodes = json.loads(data)
        for name in nodes:
            link, socket, input, output = _createNode(bmat, mat, root, name)
            links.update(link)
            sockets.update(socket)
            inputs.update(input)
            outputs.update(output)
        for node, link in links.items():
            bnode = bmat.node_tree.nodes[node]
            _setLinks(bmat, bnode, link)
        for node, socket in sockets.items():
            bnode = bmat.node_tree.nodes[node]
            _setSockets(bnode, socket)
        for node, input in inputs.items():
            bnode = bmat.node_tree.nodes[node]
            _setInputs(bnode, input)
        for node, output in outputs.items():
            bnode = bmat.node_tree.nodes[node]
            _setOutputs(bnode, output)

def _createNode(bmat, mat, root, name):
    links = {}
    sockets = {}
    inputs = {}
    outputs = {}
    data = mat.Material.get(root + '.' + name)
    if data:
        node = json.loads(data)
        print(f"Create Node socket {name} of type {node['Type']}")
        bnode = bmat.node_tree.nodes.new(type=node['Type'])
        bnode.name = name
        links[bnode.name] = node['Link']
        sockets[bnode.name] = node['Sockets']
        inputs[bnode.name] = node['Inputs']
        outputs[bnode.name] = node['Outputs']
    return links, sockets, inputs, outputs

def _setLinks(bmat, bnode, links):
    for input, outputs in links.items():
        _setLink(bmat, bnode, input, *outputs)

def _setLink(bmat, bnode, input, node2, output):
    bmat.node_tree.links.new(bmat.node_tree.nodes[node2].outputs[output],
                             bnode.inputs[input])

def _setSockets(obj, sockets):
    for property, value in sockets.items():
        if isinstance(value, dict):
            if property.isnumeric():
                _setSockets(obj[int(property)], value)
            else:
                _setSockets(getattr(obj, property), value)
        else:
            setattr(obj, property, value)

def _setInputs(bnode, inputs):
    for input, value in inputs.items():
        binput = bnode.inputs.get(input)
        if binput:
            binput.default_value = value
        else:
            print("_setInputs() ERROR *********************************************")

def _setOutputs(bnode, outputs):
    for output, value in outputs.items():
        boutput = bnode.outputs.get(output)
        if boutput:
            boutput.default_value = value
        else:
            print("_setOutputs() ERROR *********************************************")

def _getNewCollection(bpy, name):
    bcoll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(bcoll)
    return bcoll

#==============================================================================
# Blender Operator class
#==============================================================================


class IMPORT_OT_FreeCAD(bpy.types.Operator):

    """Imports the contents of a FreeCAD .FCStd file"""
    bl_idname = 'import_fcstd.import_freecad'
    bl_label = 'Import FreeCAD FCStd file'
    bl_options = {'REGISTER', 'UNDO'}

    # ImportHelper mixin class uses this
    filename_ext = '.fcstd'

    # Properties assigned by the file selection window.
    directory : bpy.props.StringProperty(maxlen=1024, subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    files : bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})
    option_skiphidden : bpy.props.BoolProperty(name='Skip hidden objects', default=True,
        description='Only import objects that where visible in FreeCAD'
    )
    option_placement : bpy.props.BoolProperty(name='Use Placements', default=True,
        description='Set Blender pivot points to the FreeCAD placements'
    )
    option_allmaterial : bpy.props.BoolProperty(name='Create all materials', default=True,
        description='Create also unused material'
    )
    option_aspolygons : bpy.props.BoolProperty(name='Faces as polygons', default=True,
        description='Create faces as polygons when possible'
    )
    option_tessellation : bpy.props.FloatProperty(name='Tessellation', default=1.0,
        description='The tessellation value to apply when triangulating shapes'
    )
    option_scale : bpy.props.FloatProperty(name='Scaling', default=0.001,
        description='A scaling value to apply to imported objects. Default value of 0.001 means one Blender unit = 1 meter'
    )
    option_newcollection : bpy.props.BoolProperty(name='New collection', default=False,
        description='Create a new collection in the scene'
    )

    # invoke is called when the user picks our Import menu entry.
    def invoke(self, context, event):
        path = bpy.context.preferences.addons[__name__].preferences.dirpath
        if path and os.path.isdir(path):
            self.directory = path
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
    # execute is called when the user is done using the modal file-select window.
    def execute(self, context):

        dir = self.directory
        for file in self.files:
            filename = str(file.name)
            if filename.lower().endswith('.fcstd'):
                return import_fcstd(path=dir,
                                    filename=filename,
                                    skiphidden=self.option_skiphidden,
                                    placement=self.option_placement,
                                    allmaterial=self.option_allmaterial,
                                    aspolygons=self.option_aspolygons,
                                    tessellation=self.option_tessellation,
                                    scale=self.option_scale,
                                    newcollection=self.option_newcollection,
                                    report=self.report)
        return {'FINISHED'}


class IMPORT_OT_FreeCAD_Preferences(bpy.types.AddonPreferences):


    """A preferences settings dialog to set the path to the FreeCAD document"""
    bl_idname = __name__

    dirpath : bpy.props.StringProperty(name='FCStd file directory',
                                       subtype='DIR_PATH')

    def draw(self, context):
        layout = self.layout
        layout.label(text='FreeCAD default document directory path')
        layout.prop(self, 'dirpath')


class GU_PT_collection_custom_properties(bpy.types.Panel, PropertyPanel): 
    _context_path = 'collection'
    _property_type = bpy.types.Collection
    bl_label = 'Custom Properties'
    bl_idname = 'GU_PT_collection_custom_properties'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'collection'


#==============================================================================
# Register plugin with Blender
#==============================================================================

classes = (
    IMPORT_OT_FreeCAD,
    IMPORT_OT_FreeCAD_Preferences,
    GU_PT_collection_custom_properties
    )

# needed if you want to add into a dynamic menu

def menu_func_import(self, context):

    self.layout.operator(IMPORT_OT_FreeCAD.bl_idname, text='FreeCAD (.FCStd)')


def register():

    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():

    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)


if __name__ == '__main__':
    register()
