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

import bpy

import xml.sax
import zipfile
import json
import os


def importFCStd(path,
                filename='',
                skiphidden=True,
                placement=True,
                allmaterial=True,
                aspolygons=True,
                tessellation=1.0,
                scale=0.001,
                newcollection=False,
                report=None):

    # reads a FreeCAD .FCStd file and creates Blender objects
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
    guidata = {}
    zdoc = zipfile.ZipFile(path + filename)
    if zdoc:
        if 'GuiDocument.xml' in zdoc.namelist():
            gf = zdoc.open('GuiDocument.xml')
            data = gf.read()
            gf.close()
            Handler = XMLHandler()
            xml.sax.parseString(data, Handler)
            guidata = Handler.guidata
        zdoc.close()
    doc = FreeCAD.open(path + filename)
    docname = doc.Name
    if not doc:
        print("Unable to open the given FreeCAD file")
        if report:
            report({'ERROR'}, 'Unable to open the given FreeCAD file')
        return {'CANCELLED'}
    print (f"Transferring {len(doc.Objects)} objects to Blender")

    # import some FreeCAD modules needed below. After "import FreeCAD" these modules become available
    import Part

    def hascurves(shape):
        for e in shape.Edges:
            if not isinstance(e.Curve, (Part.Line, Part.LineSegment)):
                return True
        return False

    name, ext = os.path.splitext(filename)
    if newcollection:
        bcoll = _getNewCollection(bpy, name)
    else:
        bcoll = bpy.data.collections.get(name)
    if bcoll is None:
        bcoll = _getNewCollection(bpy, name)
        newcollection = True

    # create materials
    materials = {m.name: m for m in bpy.data.materials}
    i = 0
    if allmaterial:
        for obj in doc.Objects:
            if obj.isDerivedFrom('App::MaterialObject'):
                if obj.Label not in materials:
                    print(f"Create material: {obj.Label}")
                    bmat = bpy.data.materials.new(name=obj.Label)
                    bmat.use_nodes = True
                    bmat.node_tree.nodes.clear()
                    _setMaterialNodes(bmat, obj, root)
                    i += 1
                    materials[obj.Label] = bmat
    print(f"Create material Total: {i}")

    # for a cleaning mesh naming we need to clean orphan mesh
    for bmesh in bpy.data.meshes:
        if bmesh.users == 0:
            bpy.data.meshes.remove(bmesh)

    for obj in doc.Objects:
        print(f"Importing: {obj.Label}")
        if skiphidden:
            if obj.Name in guidata and not guidata[obj.Name]:
                print(f"{obj.Label} is invisible. Skipping.")
                continue

        verts = []
        edges = []
        faces = []
        faceedges = [] # a placeholder to store edges that belong to a face

        if obj.isDerivedFrom('Part::Feature'):
            # create mesh from shape
            print(f"Create mesh from shape: {obj.Label}")
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
            print(f"Convert freecad mesh to blender mesh: {obj.Label}")
            mesh = obj.Mesh
            if placement:
                placement = obj.Placement
                mesh = obj.Mesh.copy() # in meshes, this zeroes the placement
            t = mesh.Topology
            verts = [[v.x,v.y,v.z] for v in t[0]]
            faces = t[1]

        else:
            print(f"Can't convert FreeCAD object: {obj.Label}")

        if verts and (faces or edges):
            # create or update object with mesh and material data
            bobj = None
            bmat = None
            if not newcollection:
                # locate existing object in the collection (object with same name)
                bobj = bcoll.objects.get(obj.Label)
            if bobj:
                print(f"update object: {obj.Label}")
                # update only the mesh of existing object.
                bobj.data.clear_geometry()
                bobj.data.from_pydata(verts, edges, faces)
            else:
                # create new object
                print(f"create new object: {obj.Label}")
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
            if not allmaterial:
                continue
            if 'Material' in obj.PropertiesList:
                mat = obj.Material
                # if we have material we need to add only if it doesn't exist
                if mat and bobj.data.materials.get(mat.Label) is None:
                    if mat.Label in materials:
                        bobj.data.materials.append(materials[mat.Label])
            if 'MaterialFaces' in obj.PropertiesList:
                data = obj.MaterialFaces
                if not data:
                    continue
                mfaces = json.loads(data)
                bslot = {slot.material.name: i for i, slot in enumerate(bobj.material_slots)}
                for material, faces in mfaces.items():
                    if material not in materials:
                       continue
                    if material not in bslot:
                        bslot[material] = len(bobj.material_slots)
                        bobj.data.materials.append(materials[material])
                    slot = bslot[material]
                    for face in faces:
                        bobj.data.polygons[face].material_index = slot


    FreeCAD.closeDocument(docname)

    print("Import finished without errors")
    return {'FINISHED'}


def _setMaterialNodes(bmat, mat, root):
    links = {}
    sockets = {}
    inputs = {}
    outputs = {}
    data = mat.Material.get(root)
    print(f"_setMaterialNodes() 1 data: {data}")
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
        links[bnode.name] =   node['Link']
        sockets[bnode.name] = node['Sockets']
        inputs[bnode.name] =  node['Inputs']
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
            print(f"_setInputs() ERROR can't set node {bnode.name} input {input} default_value {value}")

def _setOutputs(bnode, outputs):
    for output, value in outputs.items():
        boutput = bnode.outputs.get(output)
        if boutput:
            boutput.default_value = value
        else:
            print(f"_setOutputs() ERROR can't set node {bnode.name} output {output} default_value {value}")

def _getNewCollection(bpy, name):
    bcoll = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(bcoll)
    return bcoll


class XMLHandler(xml.sax.ContentHandler):
    # A XML handler to process the FreeCAD GUI xml data
    # this creates a dictionary where each key is a FC object Name,
    # and each value is object Visibility

    def __init__(self):

        self.guidata = {}
        self._current = None
        self._prop = False
        self._val = None

    # call when an element starts
    def startElement(self, tag, attrs):

        if tag == 'ViewProvider':
            self._current = attrs['name']
        elif tag == 'Property' and attrs['name'] == 'Visibility':
            self._prop = True
        elif tag == 'Bool' and self._prop:
            if attrs['value'] == 'true':
                self._val = True
            else:
                self._val = False

    # call when an elements ends
    def endElement(self, tag):

        if tag == 'ViewProvider':
            if self._current and self._val is not None:
                self.guidata[self._current] = self._val
                self._current = None
                self._val = None
        elif tag == 'Property':
            if self._prop:
                self._prop = False
