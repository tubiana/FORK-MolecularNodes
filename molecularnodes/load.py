import requests
import io
from pathlib import Path

import bpy
import numpy as np
from . import coll
import warnings
from . import data
from . import color
from . import assembly
from . import nodes
from . import pkg
from . import obj
import time

bpy.types.Scene.MN_pdb_code = bpy.props.StringProperty(
    name = 'pdb_code', 
    description = 'The 4-character PDB code to download', 
    options = {'TEXTEDIT_UPDATE'}, 
    default = '1bna', 
    subtype = 'NONE', 
    maxlen = 4
    )
bpy.types.Scene.MN_cache_dir = bpy.props.StringProperty(
    name = 'cache_dir',
    description = 'Location to cache PDB files',
    options = {'TEXTEDIT_UPDATE'},
    default = str(Path('~', '.MolecularNodes').expanduser()),
    subtype = 'FILE_PATH'
)
bpy.types.Scene.MN_import_center = bpy.props.BoolProperty(
    name = "MN_import_centre", 
    description = "Move the imported Molecule on the World Origin",
    default = False
    )
bpy.types.Scene.MN_import_del_solvent = bpy.props.BoolProperty(
    name = "MN_import_del_solvent", 
    description = "Delete the solvent from the structure on import",
    default = True
    )

bpy.types.Scene.MN_import_include_bonds = bpy.props.BoolProperty(
    name = "MN_import_include_bonds", 
    description = "Include bonds in the imported structure.",
    default = True
    )
bpy.types.Scene.MN_import_panel_selection = bpy.props.IntProperty(
    name = "MN_import_panel_selection", 
    description = "Import Panel Selection", 
    subtype = 'NONE',
    default = 0
)
bpy.types.Scene.MN_import_local_path = bpy.props.StringProperty(
    name = 'path_pdb', 
    description = 'File path of the structure to open', 
    options = {'TEXTEDIT_UPDATE'}, 
    default = '', 
    subtype = 'FILE_PATH', 
    maxlen = 0
    )

bpy.types.Scene.MN_import_build_assembly = bpy.props.BoolProperty(
    name = 'Build Assembly', 
    default = False
)


bpy.types.Scene.MN_import_local_name = bpy.props.StringProperty(
    name = 'MN_name', 
    description = 'Name of the molecule on import', 
    options = {'TEXTEDIT_UPDATE'}, 
    default = 'NewMolecule', 
    subtype = 'NONE', 
    maxlen = 0
    )

bpy.types.Scene.MN_import_default_style = bpy.props.EnumProperty(
    name = "Style", 
    description = "Default style for importing molecules.", 
    items = (
        ('presets', 'Presets', 'A pre-made combination of different styles'),
        ("atoms", "Atoms", "Space-filling atoms style."), 
        ("surface", "Surface", "Solvent-accsible surface."),
        ("cartoon", "Cartoon", "Secondary structure cartoons"), 
        ("ribbon", "Ribbon", "Continuous backbone ribbon."), 
        ("ball_and_stick", "Ball and Stick", "Spheres for atoms, sticks for bonds")
    )
)


def molecule_rcsb(
    pdb_code,             
    center_molecule = False,               
    del_solvent = True,               
    include_bonds = True,   
    starting_style = 'atoms',               
    setup_nodes = True,
    cache_dir = None,
    build_assembly = False
    ):
    from biotite import InvalidFileError
    start = time.process_time()
    mol, file = open_structure_rcsb(
        pdb_code = pdb_code, 
        include_bonds=include_bonds,
        cache_dir = cache_dir
        )
    print(f'Finsihed opening molecule after {time.process_time() - start} seconds')
    
    start = time.process_time()
    print('Adding object to scene.')
    MN_object, coll_frames = create_molecule(
        MN_array = mol,
        MN_name = pdb_code,
        file = file,
        calculate_ss = False,
        center_molecule = center_molecule,
        del_solvent = del_solvent, 
        include_bonds = include_bonds
        )
    print(f'Finsihed add object after {time.process_time() - start} seconds')
    
    if setup_nodes:
        nodes.create_starting_node_tree(
            obj = MN_object, 
            coll_frames=coll_frames, 
            starting_style = starting_style
            )
    
    # MN_object['bio_transform_dict'] = file['bioAssemblyList']
    
    
    try:
        parsed_assembly_file = assembly.mmtf.MMTFAssemblyParser(file)
        MN_object['biological_assemblies'] = parsed_assembly_file.get_assemblies()
    except InvalidFileError:
        pass
    
    if build_assembly:
        obj = MN_object
        transforms_array = assembly.mesh.get_transforms_from_dict(obj['biological_assemblies'])
        data_object = assembly.mesh.create_data_object(
            transforms_array = transforms_array, 
            name = f"data_assembly_{obj.name}"
        )
        
        node_assembly = nodes.create_assembly_node_tree(
            name = obj.name, 
            iter_list = obj['chain_id_unique'], 
            data_object = data_object
            )
        group = MN_object.modifiers['MolecularNodes'].node_group
        node = nodes.add_custom_node_group_to_node(group, node_assembly.name)
        nodes.insert_last_node(group, node)
        
    
    
    return MN_object


def molecule_local(
    file_path,                    
    MN_name = "Name",                   
    include_bonds = True,                    
    center_molecule = False,                    
    del_solvent = True,                    
    default_style = 'atoms',                    
    setup_nodes = True
    ): 
    from biotite import InvalidFileError
    import biotite.structure as struc
    import os
    
    file_path = os.path.abspath(file_path)
    file_ext = os.path.splitext(file_path)[1]
    
    if file_ext == '.pdb':
        mol, file = open_structure_local_pdb(file_path, include_bonds)
        try:
            transforms = assembly.pdb.PDBAssemblyParser(file).get_assemblies()
        except InvalidFileError:
            transforms = None

    elif file_ext == '.pdbx' or file_ext == '.cif':
        mol, file = open_structure_local_pdbx(file_path, include_bonds)
        try:
            transforms = assembly.cif.CIFAssemblyParser(file).get_assemblies()
        except InvalidFileError:
            transforms = None
        
    else:
        warnings.warn("Unable to open local file. Format not supported.")
    # if include_bonds chosen but no bonds currently exist (mn.bonds is None)
    # then attempt to find bonds by distance
    if include_bonds and not mol.bonds:
        mol.bonds = struc.connect_via_distances(mol[0], inter_residue=True)
    
    if not (file_ext == '.pdb' and file.get_model_count() > 1):
        file = None
        
    
    MN_object, coll_frames = create_molecule(
        MN_array = mol,
        MN_name = MN_name,
        file = file,
        calculate_ss = True,
        center_molecule = center_molecule,
        del_solvent = del_solvent, 
        include_bonds = include_bonds
        )
    
    # setup the required initial node tree on the object 
    if setup_nodes:
        nodes.create_starting_node_tree(
            obj = MN_object,
            coll_frames = coll_frames,
            starting_style = default_style
            )
    
    if transforms:
        MN_object['biological_assemblies'] = transforms
        
    return MN_object

def get_chain_entity_id(file):
    entities = file['entityList']
    chain_names = file['chainNameList']    
    ent_dic = {}
    for i, ent in enumerate(entities):
        for chain_idx in ent['chainIndexList']:
            chain_id = chain_names[chain_idx]
            if  chain_id in ent_dic.keys():
                next
            else:
                ent_dic[chain_id] = i
    
    return ent_dic

def set_atom_entity_id(mol, file):
    mol.add_annotation('entity_id', int)
    ent_dic = get_chain_entity_id(file)
    
    entity_ids = np.array([ent_dic[x] for x in mol.chain_id])
    
    # entity_ids = chain_entity_id[chain_ids]
    mol.set_annotation('entity_id', entity_ids)
    return entity_ids

def open_structure_rcsb(pdb_code, cache_dir = None, include_bonds = True):
    import biotite.structure.io.mmtf as mmtf
    import biotite.database.rcsb as rcsb
    
    
    file = mmtf.MMTFFile.read(rcsb.fetch(pdb_code, "mmtf", target_path = cache_dir))
    
    # returns a numpy array stack, where each array in the stack is a model in the 
    # the file. The stack will be of length = 1 if there is only one model in the file
    mol = mmtf.get_structure(file, extra_fields = ["b_factor", "charge"], include_bonds = include_bonds) 
    set_atom_entity_id(mol, file)
    return mol, file

def open_structure_local_pdb(file_path, include_bonds = True):
    import biotite.structure.io.pdb as pdb
    
    file = pdb.PDBFile.read(file_path)
    
    # returns a numpy array stack, where each array in the stack is a model in the 
    # the file. The stack will be of length = 1 if there is only one model in the file
    mol = pdb.get_structure(file, extra_fields = ['b_factor', 'charge'], include_bonds = include_bonds)
    return mol, file

def open_structure_local_pdbx(file_path, include_bonds = True):
    import biotite.structure as struc
    import biotite.structure.io.pdbx as pdbx
    from biotite import InvalidFileError
    
    file = pdbx.PDBxFile.read(file_path)
    
    # returns a numpy array stack, where each array in the stack is a model in the 
    # the file. The stack will be of length = 1 if there is only one model in the file
    
    # Try to get the structure, if no structure exists try to get a small molecule
    try:
        mol  = pdbx.get_structure(file, extra_fields = ['b_factor', 'charge'])
    except InvalidFileError:
        mol = pdbx.get_component(file)

    
    
    # pdbx doesn't include bond information apparently, so manually create
    # them here if requested
    if include_bonds and not mol.bonds:
        mol[0].bonds = struc.bonds.connect_via_residue_names(mol[0], inter_residue = True)
    return mol, file

def pdb_get_b_factors(file):
    """
    Get a list, which contains a numpy array for each model containing the b-factors.
    """
    b_factors = []
    for model in range(file.get_model_count()):
        atoms = file.get_structure(model = model + 1, extra_fields = ['b_factor'])
        b_factors.append(atoms.b_factor)
    return b_factors

def get_secondary_structure(MN_array, file) -> np.array:
    """
    Gets the secondary structure annotation that is included in mmtf files and returns it as a numerical numpy array.

    Parameters:
    -----------
    MN_array : numpy.array
        The molecular coordinates array, from mmtf.get_structure()
    file : mmtf.MMTFFile
        The MMTF file containing the secondary structure information, from mmtf.MMTFFile.read()

    Returns:
    --------
    atom_sse : numpy.array
        Numerical numpy array representing the secondary structure of the molecule.
    
    Description:
    ------------
    This function uses the biotite.structure package to extract the secondary structure information from the MMTF file.
    The resulting secondary structures are `1: Alpha Helix, 2: Beta-sheet, 3: loop`.
    """
    
    from biotite.structure import spread_residue_wise
    
    sec_struct_codes = {
        -1: "X",
        0 : "I",
        1 : "S",
        2 : "H",
        3 : "E",
        4 : "G",
        5 : "B",
        6 : "T",
        7 : "C"
    }
    
    dssp_to_abc = {
        "X" : 0,
        "I" : 1, #"a",
        "S" : 3, #"c",
        "H" : 1, #"a",
        "E" : 2, #"b",
        "G" : 1, #"a",
        "B" : 2, #"b",
        "T" : 3, #"c",
        "C" : 3 #"c"
    }
    
    try:
        sse = file["secStructList"]
    except KeyError:
        ss_int = np.full(len(MN_array), 3)
        print('Warning: "secStructList" field missing from MMTF file. Defaulting \
            to "loop" for all residues.')
    else:
        ss_int = np.array(
            [dssp_to_abc.get(sec_struct_codes.get(ss)) for ss in sse], 
            dtype = int
        )
    atom_sse = spread_residue_wise(MN_array, ss_int)
    
    return atom_sse


def comp_secondary_structure(MN_array):
    """Use dihedrals to compute the secondary structure of proteins

    Through biotite built-in method derivated from P-SEA algorithm (Labesse 1997)
    Returns an array with secondary structure for each atoms where:
    - 0 = '' = non-protein or not assigned by biotite annotate_sse
    - 1 = a = alpha helix
    - 2 = b = beta sheet
    - 3 = c = coil

    Inspired from https://www.biotite-python.org/examples/gallery/structure/transketolase_sse.html
    """
    #TODO Port [PyDSSP](https://github.com/ShintaroMinami/PyDSSP)
    #TODO Read 'secStructList' field from mmtf files
    from biotite.structure import annotate_sse, spread_residue_wise

    conv_sse_char_int = {'a': 1, 'b': 2, 'c': 3, '': 0} 

    char_sse = annotate_sse(MN_array)
    int_sse = np.array([conv_sse_char_int[char] for char in char_sse], dtype=int)
    atom_sse = spread_residue_wise(MN_array, int_sse)
        
    return atom_sse

def create_molecule(MN_array, 
                    MN_name, 
                    center_molecule = False, 
                    file = None,
                    calculate_ss = False,
                    del_solvent = False, 
                    include_bonds = False,
                    starting_style = 0,
                    collection = None
                    ):
    import biotite.structure as struc
    
    MN_frames = None
    if isinstance(MN_array, struc.AtomArrayStack):
        if MN_array.stack_depth() > 1:
            MN_frames = MN_array
        MN_array = MN_array[0]
    
    # remove the solvent from the structure if requested
    if del_solvent:
        MN_array = MN_array[np.invert(struc.filter_solvent(MN_array))]

    world_scale = 0.01
    locations = MN_array.coord * world_scale
    
    centroid = np.array([0, 0, 0])
    if center_molecule:
        centroid = struc.centroid(MN_array) * world_scale
    

    # subtract the centroid from all of the positions to localise the molecule on the world origin
    if center_molecule:
        locations = locations - centroid

    if not collection:
        collection = coll.mn()
    
    bonds = []
    bond_idx = []
    if include_bonds and MN_array.bonds:
        bonds = MN_array.bonds.as_array()
        bond_idx = bonds[:, [0, 1]]
        bond_types = bonds[:, 2].copy(order = 'C') # the .copy(order = 'C') is to fix a weird ordering issue with the resulting array

    MN_object = obj.create_object(
        name = MN_name, 
        collection = collection, 
        locations = locations, 
        bonds = bond_idx
        )
    

    # The attributes for the model are initially defined as single-use functions. This allows
    # for a loop that attempts to add each attibute by calling the function. Only during this
    # loop will the call fail if the attribute isn't accessible, and the warning is reported
    # there rather than setting up a try: except: for each individual attribute which makes
    # some really messy code.
    
    # I still don't like this as an implementation, and welcome any cleaner approaches that 
    # anybody might have.
    
    def att_atomic_number():
        atomic_number = np.array(list(map(
            lambda x: data.elements.get(x, {'atomic_number': -1}).get("atomic_number"), 
            np.char.title(MN_array.element))))
        return atomic_number
    
    def att_res_id():
        return MN_array.res_id
    
    def att_res_name():
        other_res = []
        counter = 0
        id_counter = -1
        res_names = MN_array.res_name
        res_names_new = []
        res_ids = MN_array.res_id
        res_nums  = []
        
        for name in res_names:
            res_num = data.residues.get(name, {'res_name_num': -1}).get('res_name_num')
            
            if res_num == 9999:
                if res_names[counter - 1] != name or res_ids[counter] != res_ids[counter - 1]:
                    id_counter += 1
                
                unique_res_name = str(id_counter + 100) + "_" + str(name)
                other_res.append(unique_res_name)
                
                num = np.where(np.isin(np.unique(other_res), unique_res_name))[0][0] + 100
                res_nums.append(num)
            else:
                res_nums.append(res_num)
            counter += 1

        MN_object['ligands'] = np.unique(other_res)
        return np.array(res_nums)

    
    def att_chain_id():
        chain_id = np.searchsorted(np.unique(MN_array.chain_id), MN_array.chain_id)
        return chain_id
    
    def att_entity_id():
        return MN_array.entity_id
    
    def att_b_factor():
        return MN_array.b_factor
    
    def att_vdw_radii():
        vdw_radii =  np.array(list(map(
            # divide by 100 to convert from picometres to angstroms which is what all of coordinates are in
            lambda x: data.elements.get(x, {'vdw_radii': 100}).get('vdw_radii', 100) / 100,  
            np.char.title(MN_array.element)
            )))
        return vdw_radii * world_scale
    
    def att_atom_name():
        atom_name = np.array(list(map(
            lambda x: data.atom_names.get(x, -1), 
            MN_array.atom_name
        )))
        
        return atom_name

    def att_lipophobicity():
        lipo = np.array(list(map(
            lambda x, y: data.lipophobicity.get(x, {"0": 0}).get(y, 0),
            MN_array.res_name, MN_array.atom_name
        )))
        
        return lipo
    
    def att_charge():
        charge = np.array(list(map(
            lambda x, y: data.atom_charge.get(x, {"0": 0}).get(y, 0),
            MN_array.res_name, MN_array.atom_name
        )))
        return charge
    
    def att_color():
        return color.color_chains(att_atomic_number(), att_chain_id()).reshape(-1)
    
    def att_is_alpha():
        return np.isin(MN_array.atom_name, 'CA')
    
    def att_is_solvent():
        return struc.filter_solvent(MN_array)
    
    def att_is_backbone():
        """
        Get the atoms that appear in peptide backbone or nucleic acid phosphate backbones.
        Filter differs from the Biotite's `struc.filter_peptide_backbone()` in that this
        includes the peptide backbone oxygen atom, which biotite excludes. Additionally 
        this selection also includes all of the atoms from the ribose in nucleic acids, 
        and the other phosphate oxygens.
        """
        backbone_atom_names = [
            'N', 'C', 'CA', 'O',                    # peptide backbone atoms
            "P", "O5'", "C5'", "C4'", "C3'", "O3'", # 'continuous' nucleic backbone atoms
            "O1P", "OP1", "O2P", "OP2",             # alternative names for phosphate O's
            "O4'", "C1'", "C2'", "O2'"              # remaining ribose atoms
        ]
        
        is_backbone = np.logical_and(
            np.isin(MN_array.atom_name, backbone_atom_names), 
            np.logical_not(struc.filter_solvent(MN_array))
        )
        return is_backbone
    
    def att_is_nucleic():
        return struc.filter_nucleotides(MN_array)
    
    def att_is_peptide():
        aa = struc.filter_amino_acids(MN_array)
        con_aa = struc.filter_canonical_amino_acids(MN_array)
        
        return aa | con_aa
    
    def att_is_hetero():
        return MN_array.hetero
    
    def att_is_carb():
        return struc.filter_carbohydrates(MN_array)

    def att_sec_struct():
        if calculate_ss or not file:
            return comp_secondary_structure(MN_array)
        else:
            return get_secondary_structure(MN_array, file)
    

    # Add information about the bond types to the model on the edge domain
    # Bond types: 'ANY' = 0, 'SINGLE' = 1, 'DOUBLE' = 2, 'TRIPLE' = 3, 'QUADRUPLE' = 4
    # 'AROMATIC_SINGLE' = 5, 'AROMATIC_DOUBLE' = 6, 'AROMATIC_TRIPLE' = 7
    # https://www.biotite-python.org/apidoc/biotite.structure.BondType.html#biotite.structure.BondType
    if include_bonds:
        try:
            obj.add_attribute(
                object = MN_object, 
                name = 'bond_type', 
                data = bond_types, 
                type = "INT", 
                domain = "EDGE"
                )
        except:
            warnings.warn('Unable to add bond types to the molecule.')

    
    # these are all of the attributes that will be added to the structure
    # TODO add capcity for selection of particular attributes to include / not include to potentially
    # boost performance, unsure if actually a good idea of not. Need to do some testing.
    attributes = (
        {'name': 'res_id',          'value': att_res_id,              'type': 'INT',     'domain': 'POINT'},
        {'name': 'res_name',        'value': att_res_name,            'type': 'INT',     'domain': 'POINT'},
        {'name': 'atomic_number',   'value': att_atomic_number,       'type': 'INT',     'domain': 'POINT'},
        {'name': 'b_factor',        'value': att_b_factor,            'type': 'FLOAT',   'domain': 'POINT'},
        {'name': 'vdw_radii',       'value': att_vdw_radii,           'type': 'FLOAT',   'domain': 'POINT'},
        {'name': 'chain_id',        'value': att_chain_id,            'type': 'INT',     'domain': 'POINT'},
        {'name': 'entity_id',       'value': att_entity_id,           'type': 'INT',     'domain': 'POINT'},
        {'name': 'atom_name',       'value': att_atom_name,           'type': 'INT',     'domain': 'POINT'},
        {'name': 'lipophobicity',   'value': att_lipophobicity,       'type': 'FLOAT',   'domain': 'POINT'},
        {'name': 'charge',          'value': att_charge,              'type': 'FLOAT',   'domain': 'POINT'},
        {'name': 'Color',           'value': att_color,               'type': 'FLOAT_COLOR',   'domain': 'POINT'},
        
        {'name': 'is_backbone',     'value': att_is_backbone,         'type': 'BOOLEAN', 'domain': 'POINT'},
        {'name': 'is_alpha_carbon', 'value': att_is_alpha,            'type': 'BOOLEAN', 'domain': 'POINT'},
        {'name': 'is_solvent',      'value': att_is_solvent,          'type': 'BOOLEAN', 'domain': 'POINT'},
        {'name': 'is_nucleic',      'value': att_is_nucleic,          'type': 'BOOLEAN', 'domain': 'POINT'},
        {'name': 'is_peptide',      'value': att_is_peptide,          'type': 'BOOLEAN', 'domain': 'POINT'},
        {'name': 'is_hetero',       'value': att_is_hetero,           'type': 'BOOLEAN', 'domain': 'POINT'},
        {'name': 'is_carb',         'value': att_is_carb,             'type': 'BOOLEAN', 'domain': 'POINT'},
        {'name': 'sec_struct',      'value': att_sec_struct,          'type': 'INT',     'domain': 'POINT'}
    )
    
    # assign the attributes to the object
    for att in attributes:
        start = time.process_time()
        try:
            obj.add_attribute(MN_object, att['name'], att['value'](), att['type'], att['domain'])
            print(f'Added {att["name"]} after {time.process_time() - start} s')
        except :
            warnings.warn(f"Unable to add attribute: {att['name']}")
            print(f'Failed adding {att["name"]} after {time.process_time() - start} s')

    if MN_frames:
        try:
            b_factors = pdb_get_b_factors(file)
        except:
            b_factors = None
        
        coll_frames = coll.frames(MN_object.name, parent = coll.data())
        
        for i, frame in enumerate(MN_frames):
            obj_frame = obj.create_object(
                name = MN_object.name + '_frame_' + str(i), 
                collection=coll_frames, 
                locations= frame.coord * world_scale - centroid
            )
            if b_factors:
                try:
                    obj.add_attribute(obj_frame, 'b_factor', b_factors[i])
                except:
                    b_factors = False
        
        # disable the frames collection so it is not seen
        # bpy.context.view_layer.layer_collection.children[''].children[coll_frames.name].exclude = True
    else:
        coll_frames = None
    
    # add custom properties to the actual blender object, such as number of chains, biological assemblies etc
    # currently biological assemblies can be problematic to holding off on doing that
    try:
        MN_object['chain_id_unique'] = list(np.unique(MN_array.chain_id))
    except:
        warnings.warn('No chain information detected.')
    
    try: 
        MN_object['entity_names'] = [ent['description'] for ent in file['entityList']]
    except:
        pass
    
    return MN_object, coll_frames

# operator that calls the function to import the structure from the PDB
class MN_OT_Import_Protein_RCSB(bpy.types.Operator):
    bl_idname = "mn.import_protein_rcsb"
    bl_label = "import_protein_fetch_pdb"
    bl_description = "Download and open a structure from the Protein Data Bank"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return not False

    def execute(self, context):
        pdb_code = context.scene.MN_pdb_code
        
        MN_object = molecule_rcsb(
            pdb_code=pdb_code,
            center_molecule=context.scene.MN_import_center, 
            del_solvent=context.scene.MN_import_del_solvent,
            include_bonds=context.scene.MN_import_include_bonds,
            starting_style=context.scene.MN_import_default_style,
            cache_dir=context.scene.MN_cache_dir, 
            build_assembly = bpy.context.scene.MN_import_build_assembly
        )
        
        bpy.context.view_layer.objects.active = MN_object
        self.report({'INFO'}, message=f"Imported '{pdb_code}' as {MN_object.name}")
        
        return {"FINISHED"}

    def invoke(self, context, event):
        return self.execute(context)

# operator that calls the function to import the structure from a local file
class MN_OT_Import_Protein_Local(bpy.types.Operator):
    bl_idname = "mn.import_protein_local"
    bl_label = "import_protein_local"
    bl_description = "Open a local structure file"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return not False

    def execute(self, context):
        file_path = context.scene.MN_import_local_path
        
        MN_object = molecule_local(
            file_path=file_path, 
            MN_name=context.scene.MN_import_local_name,
            include_bonds=context.scene.MN_import_include_bonds, 
            center_molecule=context.scene.MN_import_center, 
            del_solvent=context.scene.MN_import_del_solvent, 
            default_style=context.scene.MN_import_default_style, 
            setup_nodes=True
            
            )
        
        # return the good news!
        bpy.context.view_layer.objects.active = MN_object
        self.report({'INFO'}, message=f"Imported '{file_path}' as {MN_object.name}")
        return {"FINISHED"}

    def invoke(self, context, event):
        return self.execute(context)