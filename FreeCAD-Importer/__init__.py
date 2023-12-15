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
from rna_prop_ui import PropertyPanel
from bpy_extras.io_utils import ImportHelper

import os

from .helper import importFCStd


bl_info = {'name':        'FreeCAD-Importer',
           'category':    'Import-Export',
           'author':      'prrvchr',
           'version':     (0, 0, 2),
           'blender':     (3, 0, 1),
           'location':    'File > Import > FreeCAD',
           'description': 'Imports files from FreeCAD. Only Part and Mesh objects are supported.'}


class ImportFreeCAD(bpy.types.Operator, ImportHelper):

    """Imports the contents of a FreeCAD .FCStd file"""
    bl_idname =  'import_fcstd.import_freecad'
    bl_label =   'Import FreeCAD FCStd file'
    bl_options = {'REGISTER', 'UNDO'}

    # ImportHelper mixin class uses this
    filter_glob: bpy.props.StringProperty(default='*.fcstd', options={'HIDDEN'})
    directory:   bpy.props.StringProperty(maxlen=1024, subtype='FILE_PATH', options={'HIDDEN', 'SKIP_SAVE'})
    files:       bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement, options={'HIDDEN', 'SKIP_SAVE'})

    option_skiphidden:    bpy.props.BoolProperty(name='Skip hidden objects', default=True,
                          description='Only import objects that where visible in FreeCAD')

    option_placement:     bpy.props.BoolProperty(name='Use Placements', default=True,
                          description='Set Blender pivot points to the FreeCAD placements')

    option_allmaterial:   bpy.props.BoolProperty(name='Create all materials', default=True,
                          description='Create also unused material')

    option_aspolygons:    bpy.props.BoolProperty(name='Faces as polygons', default=True,
                          description='Create faces as polygons when possible')

    option_tessellation:  bpy.props.FloatProperty(name='Tessellation', default=1.0,
                          description='The tessellation value to apply when triangulating shapes')

    option_scale:         bpy.props.FloatProperty(name='Scaling', default=0.001, precision=3,
                          description='A scaling value to apply to imported objects. Default value of 0.001 means one Blender unit = 1 meter')

    option_newcollection: bpy.props.BoolProperty(name='New collection', default=False,
                          description='Create a new collection in the scene')

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
                return importFCStd(path=dir,
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


class ImportPreferences(bpy.types.AddonPreferences):
    """A preferences settings dialog to set the path to the FreeCAD document"""
    bl_idname = __name__

    dirpath : bpy.props.StringProperty(name='FCStd file directory',
                                       subtype='DIR_PATH')

    def draw(self, context):
        layout = self.layout
        layout.label(text='FreeCAD default document directory path')
        layout.prop(self, 'dirpath')


class CustomProperties(bpy.types.Panel, PropertyPanel): 
    _context_path = 'collection'
    _property_type = bpy.types.Collection
    bl_label = 'Custom Properties'
    bl_idname = 'GU_PT_collection_custom_properties'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'collection'


# register plugin with Blender

classes = (ImportFreeCAD,
           ImportPreferences,
           CustomProperties)

# needed if you want to add into a dynamic menu
def _menuImport(self, context):
    self.layout.operator(ImportFreeCAD.bl_idname, text='FreeCAD (.FCStd)')


def register():
    from bpy.utils import register_class
    for cls in classes:
        register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menuImport)


def unregister():
    from bpy.utils import unregister_class
    for cls in reversed(classes):
        unregister_class(cls)
    bpy.types.TOPBAR_MT_file_import.remove(_menuImport)


if __name__ == '__main__':
    register()
