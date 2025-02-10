import argparse
import ast
import copy
import dataclasses
import glob
import itertools
import json
import more_itertools
import numpy
import os
import re
import socket
import subprocess
import sys
import tqdm

from ruamel.yaml import YAML
yaml = YAML()
yaml.preserve_quotes = True
yaml.width = 1024

import ROOT
ROOT.gROOT.SetBatch(1)

#sys.path.append(f"{os.getcwd()}/scripts")
sys.path.append(os.path.split(os.path.realpath(__file__))[0])

import constants
import cms_lumi
import tdrstyle


class Formatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawTextHelpFormatter
): pass



@dataclasses.dataclass(init = True)
class SiPMArray :
    
    barcode: str = None
    id: str = None
    tec_res: float = None
    
    def dict(self) :
        
        return dataclasses.asdict(self)


@dataclasses.dataclass(init = True)
class SensorModule :
    
    barcode: str = None
    id: str = None
    lyso: str = None
    sipm1: str = None
    sipm2: str = None
    prod_datime: str = None
    
    def dict(self) :
        
        return dataclasses.asdict(self)


@dataclasses.dataclass(init = True)
class DetectorModule :
    
    barcode: str = None
    id: str = None
    feb: str = None
    sm1: str = None
    sm2: str = None
    prod_datime: str = None
    
    def dict(self) :
        
        return dataclasses.asdict(self)


class DictClass:
     
    def __init__(self, dict):
        self.__dict__.update(dict)


def dict_to_obj(dict):
     
    return json.loads(json.dumps(dict), object_hook = DictClass)

def run_cmd_list(l_cmd, debug = False) :
    
    for cmd in l_cmd :
        
        if (debug) :
            
            print(f"Trying command: {cmd}")
        
        retval = os.system(cmd)
        
        if (retval) :
            
            exit()


def natural_sort(l):
    
    convert = lambda text: int(text) if text.isdigit() else text.lower()
    alphanum_key = lambda key: [convert(c) for c in re.split('([0-9]+)', key)]
    return sorted(l, key = alphanum_key)


def parse_string_regex(
    s,
    regexp
) :
    
    rgx = re.compile(regexp)
    result = [m.groupdict() for m in rgx.finditer(s)][0]
    
    return result


def get_file_list(
    l_srcs,
    regexp
) :
    """
    Get the list of files with specified regular expression
    """
    rgx = re.compile(regexp)
    
    l_fnames = []
    
    for src in tqdm.tqdm(l_srcs) :
        
        while "//" in src:
            
            src = src.replace("//", "/")
        
        l_tmp = glob.glob(f"{src}/**", recursive = True)
        l_tmp = [_f for _f in l_tmp if os.path.isfile(_f) and rgx.search(_f)]
        l_fnames.extend(l_tmp)
    
    return l_fnames


def is_tunnel_open(port = 8113) :
    
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        
        return s.connect_ex(("localhost", port)) == 0


def get_part_ids(barcode_min, barcode_max) :
    """
    Get part IDs for a range of barcodes
    """
    
    assert is_tunnel_open(port = 8113), "Open tunnel to database first."
    
    dbquery_output = subprocess.run([
        "./python/rhapi.py",
        "-u", "http://localhost:8113",
        "-a",
        "-f", "json2",
        #f"select s.ID,s.BARCODE from mtd_cmsr.parts s where s.BARCODE >= '{barcode_min}' and s.BARCODE <='{barcode_max}'"
        f"select s.* from mtd_cmsr.parts s where s.BARCODE >= '{barcode_min}' and s.BARCODE <='{barcode_max}'"
    ], stdout = subprocess.PIPE, check = True)
    
    dbquery_output = dbquery_output.stdout.decode("utf-8")
    l_infodicts = ast.literal_eval(dbquery_output)["data"]
    
    return l_infodicts


def get_part_barcodes(
    parttype,
    location_id = None
    ) :
    """
    Get list of part barcodes
    """
    
    assert is_tunnel_open(port = 8113), "Open tunnel to database first."
    
    query = f"select s.BARCODE from mtd_cmsr.parts s where s.KIND_OF_PART = '{parttype}'"
    #query = f"select s.* from mtd_cmsr.parts s where s.KIND_OF_PART = '{parttype}'"
    
    if (location_id is not None) :
        
        query = f"{query} AND s.LOCATION_ID = {location_id}"
    
    dbquery_output = subprocess.run([
        "./python/rhapi.py",
        "-u", "http://localhost:8113",
        "-a",
        query
    ], stdout = subprocess.PIPE, check = True)
    
    l_part_barcode = dbquery_output.stdout.decode("utf-8").split()[1:]
    l_part_barcode = [_barcode.strip() for _barcode in l_part_barcode]
    
    return l_part_barcode


def get_daughter_info(
    parent_barcode_min,
    parent_barcode_max,
    ) :
    """
    Get list of daughter information dictionaries for a range of parent barcodes
    """
    
    assert is_tunnel_open(port = 8113), "Open tunnel to database first."
    
    l_parent_infodicts = get_part_ids(
        barcode_min = parent_barcode_min,
        barcode_max = parent_barcode_max
    )
    
    l_parent_ids = [_info["id"] for _info in l_parent_infodicts]
    
    dbquery_output = subprocess.run([
        "./python/rhapi.py",
        "-u", "http://localhost:8113",
        "-a",
        "-f", "json2",
        #f"select s.PART_PARENT_ID,s.BARCODE,s.KIND_OF_PART from mtd_cmsr.parts s where s.PART_PARENT_ID in {str(tuple(l_parent_ids)).replace(',)', ')')}" # Remove the trailing comma in a single element tuple: (X,)
        f"select s.* from mtd_cmsr.parts s where s.PART_PARENT_ID in {str(tuple(l_parent_ids)).replace(',)', ')')}" # Remove the trailing comma in a single element tuple: (X,)
    ], stdout = subprocess.PIPE, check = True)
    
    dbquery_output = dbquery_output.stdout.decode("utf-8")
    
    l_daughter_infodicts = ast.literal_eval(dbquery_output)["data"]
    
    # Insert the parent barcode in each daughter part dictionary
    for infodict in l_daughter_infodicts :
        
        parent_info = next((_pinfo for _pinfo in l_parent_infodicts if _pinfo["id"] == infodict["partParentId"]), None)
        assert (parent_info is not None), "Could not find parent"
        infodict["parentBarcode"] = parent_info["barcode"]
    
    return l_parent_infodicts, l_daughter_infodicts


def get_used_sm_barcodes(location_id = None, yamlfile = None, d_dms = None) :
    """
    Get list of all used (assembled into DMs) SM barcodes
    If yamlfile is provided, will load existing information from there
    If fetch additional DM info from the database if they are not in the file
    """
    
    # Show all columns:
    # ./rhapi.py -u http://localhost:8113 "select s.* from mtd_cmsr.parts s where s.KIND_OF_PART = 'DetectorModule'"
    
    d_dms = get_all_part_info(
        parttype = constants.DM.KIND_OF_PART,
        yamlfile = yamlfile,
        location_id = location_id,
    )
    
    l_sm_barcodes = list(itertools.chain(*[[_dm.sm1, _dm.sm2] for _dm in d_dms.values()]))
    
    return l_sm_barcodes


def get_sipm_tec_res(
    barcode_min,
    barcode_max
) :
    assert is_tunnel_open(port = 8113), "Open tunnel to database first."
    
    dbquery_output = subprocess.run([
        "./python/rhapi.py",
        "-u", "http://localhost:8113",
        "-a",
        "-f", "json2",
        f"select s.part_barcode,s.rac from mtd_cmsr.c3060 s where s.part_barcode >= '{barcode_min}' and s.part_barcode <= '{barcode_max}'"
    ], stdout = subprocess.PIPE, check = True)
    
    dbquery_output = dbquery_output.stdout.decode("utf-8")
    
    l_tecdicts = ast.literal_eval(dbquery_output)["data"]
    
    d_tec_res = {}
    
    for tec in l_tecdicts :
        
        try :
            
            barcode = tec["partBarcode"]
            tec_res = float(tec["rac"])
            d_tec_res[barcode] = tec_res
        
        except Exception as err:
            
            print(f"Error getting TEC resistance of: {tec}")
            print(err)
    
    return d_tec_res


def check_parttype(parttype) :
    
    assert parttype in [
        constants.SIPM.KIND_OF_PART,
        constants.LYSO.KIND_OF_PART,
        constants.SM.KIND_OF_PART,
        constants.FE.KIND_OF_PART,
        constants.DM.KIND_OF_PART,
    ]


def get_part_info(
        barcode_min,
        barcode_max,
        parttype
    ) :
    """
    Get part information
    """
    
    check_parttype(parttype)
    
    d_parts = {}
    
    if (parttype == constants.SM.KIND_OF_PART) :
        
        l_parent_infodicts, l_daughter_infodicts = get_daughter_info(
            parent_barcode_min = barcode_min,
            parent_barcode_max = barcode_max
        )
        
        print(f"Fetched information for {len(l_parent_infodicts)} {parttype}(s) from the database. Processing ...")
        for pinfodict in tqdm.tqdm(l_parent_infodicts) :
            
            id = pinfodict["id"]
            barcode = pinfodict["barcode"]
            prod_datime = pinfodict["productionDate"]
        
            lyso = next((_info["barcode"] for _info in l_daughter_infodicts if (_info["kindOfPart"] == constants.LYSO.KIND_OF_PART and _info["partParentId"] == id)), None)
            l_sipms = natural_sort([_info["barcode"] for _info in l_daughter_infodicts if (_info["kindOfPart"] == constants.SIPM.KIND_OF_PART and _info["partParentId"] == id)])
            part = None
            
            if (lyso is None or len(l_sipms) != 2) :
                
                print(f"Error fetching parts for {parttype} {barcode} :")
                print(f"  LYSO: {lyso}")
                print(f"  SiPM: {l_sipms}")
            
            else :
                
                part = SensorModule(
                    id = str(id),
                    barcode = str(barcode),
                    lyso = str(lyso),
                    sipm1 = l_sipms[0],
                    sipm2 = l_sipms[1],
                    prod_datime = prod_datime
                )
            
            d_parts[barcode] = part
    
    
    elif (parttype == constants.DM.KIND_OF_PART) :
        
        l_parent_infodicts, l_daughter_infodicts = get_daughter_info(
            parent_barcode_min = barcode_min,
            parent_barcode_max = barcode_max
        )
        
        print(f"Fetched information for {len(l_parent_infodicts)} {parttype}(s) from the database. Processing ...")
        for pinfodict in tqdm.tqdm(l_parent_infodicts) :
            
            id = pinfodict["id"]
            barcode = pinfodict["barcode"]
            prod_datime = pinfodict["productionDate"]
            
            feb = next((_info["barcode"] for _info in l_daughter_infodicts if (_info["kindOfPart"] == constants.FE.KIND_OF_PART and _info["partParentId"] == id)), None)
            l_sms = natural_sort([_info["barcode"] for _info in l_daughter_infodicts if (_info["kindOfPart"] == constants.SM.KIND_OF_PART and _info["partParentId"] == id)])
            part = None
            
            if (feb is None or len(l_sms) != 2) :
                
                print(f"Error fetching parts for {parttype} {barcode} :")
                print(f"  FEB: {feb}")
                print(f"  SM: {l_sms}")
            
            else :
                
                part = DetectorModule(
                    id = str(id),
                    barcode = str(barcode),
                    feb = str(feb),
                    sm1 = l_sms[0],
                    sm2 = l_sms[1],
                    prod_datime = prod_datime
                )
            
            d_parts[barcode] = part
    
    
    elif (parttype == constants.SIPM.KIND_OF_PART) :
        
        l_infodicts = get_part_ids(barcode_min = barcode_min, barcode_max = barcode_max)
        d_tec_res = get_sipm_tec_res(barcode_min = barcode_min, barcode_max = barcode_max)
        
        print(f"Fetched information for {len(l_infodicts)} {parttype}(s) from the database. Processing ...")
        for infodict in tqdm.tqdm(l_infodicts) :
            
            id = infodict["id"]
            barcode = infodict["barcode"]
            tec_res = d_tec_res[barcode]
            
            part = SiPMArray(
                id = str(id),
                barcode = str(barcode),
                tec_res = tec_res
            )
            
            d_parts[barcode] = part
    
    return d_parts


def get_all_part_info(parttype, location_id = None, yamlfile = None, nodb = False) :
    """
    Get the information for all parts
    If yamlfile is provided, will load the information from there
    Will fetch the information of addtional SMs from the database if they are not in the file
    """
    
    check_parttype(parttype)
    
    d_parts = load_part_info(parttype = parttype, yamlfile = yamlfile) if yamlfile else {}
    
    if (not nodb) :
         
        print(f"Fetching {parttype} information from the database ... ")
        l_part_barcodes = get_part_barcodes(parttype = parttype, location_id = location_id)
        print(f"Found {len(l_part_barcodes)} {parttype}(s) on the database.")
        
        # Only fetch the ones that have not already been loaded
        l_part_barcodes = list(set(l_part_barcodes) - set(list(d_parts.keys())))
        print(f"Fetching {len(l_part_barcodes)} {parttype}(s) from the database ...")
        
        # Group the barcodes and then use ranges to fetch from database
        # Significantly faster than looping over barcodes
        l_part_barcodes_int = sorted([int(_bc) for _bc in l_part_barcodes])
        l_barcode_groups_tmp = [list(group) for group in more_itertools.consecutive_groups(l_part_barcodes_int)]
        
        # Merge groups if they span < 500
        # Otherwise there can be too many groups which takes a long time to query
        # However, this may add additional barcodes that are not needed (such as those not at the desired location)
        # Filter them out later
        l_barcode_groups = []
        for igroup, group in enumerate(l_barcode_groups_tmp) :
            
            if (not l_barcode_groups) :
                
                l_barcode_groups.append(group)
            
            else :
                
                barcode_min = l_barcode_groups[-1][0]
                barcode_max = group[-1] if (len(group) > 1) else group[0]
                
                if (barcode_max-barcode_min) < 500 :
                    
                    l_barcode_groups[-1].extend(group)
                
                else :
                    
                    l_barcode_groups.append(group)
        
        for igroup, group in enumerate(l_barcode_groups) :
            
            #print(group)
            barcode_min = group[0]
            barcode_max = group[-1] if (len(group) > 1) else group[0]
            
            print(f"Fetching barcode group {igroup+1}/{len(l_barcode_groups)} having {len(group)} {parttype}(s) ...")
            
            d_parts_fetched = get_part_info(
                barcode_min = str(barcode_min),
                barcode_max = str(barcode_max),
                parttype = parttype
            )
            
            # Filter out the additional barcodes
            d_parts_fetched = {_key: _val for _key, _val in d_parts_fetched.items() if _key in l_part_barcodes}
            
            d_parts.update(d_parts_fetched)
    
    print(f"Found information for {len(d_parts)} {parttype}(s) in total.")
    
    return d_parts


def load_part_info(parttype, yamlfile) :
    """
    Load part info from yamlfile
    """
    
    check_parttype(parttype)
    
    d_parts = {}
    
    if (os.path.exists(yamlfile)) :
        
        print(f"Loading {parttype} information from file: {yamlfile} ...")
        
        with open(yamlfile, "r") as fopen :
            
            d_parts = yaml.load(fopen.read())#, Loader = yaml.RoundTripLoader)
        
        # Convert dict to SensorModule object
        if (parttype == constants.SIPM.KIND_OF_PART) :
            
            d_parts = {_key: SiPMArray(**_val) for _key, _val in d_parts.items()}
        
        elif (parttype == constants.SM.KIND_OF_PART) :
            
            d_parts = {_key: SensorModule(**_val) for _key, _val in d_parts.items()}
        
        elif (parttype == constants.DM.KIND_OF_PART) :
            
            d_parts = {_key: DetectorModule(**_val) for _key, _val in d_parts.items()}
        
        print(f"Loaded information for {len(d_parts)} {parttype}(s).")
    
    else :
        
        print(f"{parttype} information file ({yamlfile}) does not exist. No {parttype} information loaded.")
    
    return d_parts


def combine_parts(d_sipms, d_sms, d_dms) :
    
    for sm, sminfo in d_sms.items() :
        
        sminfo.sipm1 = d_sipms.get(sminfo.sipm1, sminfo.sipm1)
        sminfo.sipm2 = d_sipms.get(sminfo.sipm2, sminfo.sipm2)
    
    for dm, dminfo in d_dms.items() :
        
        dminfo.sm1 = d_sms.get(dminfo.sm1, dminfo.sm1)
        dminfo.sm2 = d_sms.get(dminfo.sm2, dminfo.sm2)


def save_all_part_info(parttype, outyamlfile, inyamlfile = None, location_id = None, ret = False, nodb = False) :
    """
    Load existing part info from inyamlfile
    Fetch additional part info from database
    Save all part info into outyamlfile
    """
    
    check_parttype(parttype)
    
    d_parts_orig = get_all_part_info(parttype = parttype, yamlfile = inyamlfile, location_id = location_id, nodb = nodb)
    
    # Convert Module object to dict
    d_parts = {_key: _val.dict() for _key, _val in d_parts_orig.items() if _val}
    
    outdir = os.path.dirname(outyamlfile)
    
    if len(outdir) :
        
        os.system(f"mkdir -p {outdir}")
    
    print(f"Saving {parttype} information to file: {outyamlfile} ...")
    
    with open(outyamlfile, "w") as fopen :
        
        yaml.dump(d_parts, fopen)
    
    print(f"Saved information for {len(d_parts)} {parttype}(s).")
    
    if ret :
        
        return d_parts_orig


def handle_flows(hist, underflow = True, overflow = True) :
    
    nbins = hist.GetNbinsX()
    
    if (underflow) :
        
        hist.AddBinContent(1, hist.GetBinContent(0))
        hist.SetBinContent(0, 0.0)
        hist.SetBinError(0, 0.0)
    
    if (overflow) :
        
        hist.AddBinContent(nbins, hist.GetBinContent(nbins+1))
        hist.SetBinContent(nbins+1, 0.0)
        hist.SetBinError(nbins+1, 0.0)


def get_canvas(ratio = False) :
    
    #ROOT.gROOT.LoadMacro(os.path.split(os.path.realpath(__file__))[0]+"/tdrstyle.C")
    #ROOT.gROOT.ProcessLine("setTDRStyle();")
    
    tdrstyle.setTDRStyle()
    
    #ROOT.gROOT.SetStyle("tdrStyle")
    ROOT.gROOT.ForceStyle(True)
    
    ROOT.gStyle.SetPadTickX(0)
    ROOT.gStyle.SetHatchesSpacing(7*ROOT.gStyle.GetHatchesSpacing())
    ROOT.gStyle.SetHatchesLineWidth(1)
    
    canvas = ROOT.TCanvas("canvas", "canvas", 1600, 1300)
    canvas.UseCurrentStyle()
    
    
    if (ratio) :
        
        canvas.Divide(1, 2)
        
        canvas.cd(1).SetPad(0, 0.32, 1, 1)
        canvas.cd(1).SetTopMargin(0.075)
        canvas.cd(1).SetBottomMargin(0)
        
        canvas.cd(2).SetPad(0, 0.0, 1, 0.3)
        canvas.cd(2).SetTopMargin(0.05)
        canvas.cd(2).SetBottomMargin(0.285)
        
        canvas.cd(2).SetLeftMargin(0.125)
        canvas.cd(2).SetRightMargin(0.05)
    
    else :
        
        #canvas.SetLeftMargin(0.16)
        #canvas.SetRightMargin(0.05)
        canvas.SetTopMargin(0.05)
        #canvas.SetBottomMargin(0.135)
        canvas.SetLeftMargin(0.125)
        canvas.SetRightMargin(0.05)

    
    return canvas


def get_draw_opt(obj) :
    
    drawopt = obj.GetHistogram().GetOption() if hasattr(obj, "GetHistogram") else obj.GetOption()
    drawopt = drawopt.replace("hist", "L")
    drawopt = f"{drawopt}F" if obj.GetFillStyle() else drawopt
    
    return drawopt


def root_plot1D(
    l_hist,
    outfile,
    xrange,
    yrange,
    ratio_num_den_pairs = [],
    l_hist_overlay = [],
    l_graph_overlay = [],
    ratio_mode = "mc",
    no_xerror = False,
    logx = False,
    logy = False,
    xtitle = "",
    ytitle = "",
    timeformatx = "",
    xtitle_ratio = "",
    ytitle_ratio = "",
    yrange_ratio = (0, 2),
    centertitlex = True,
    centertitley = True,
    centerlabelx = False,
    centerlabely = False,
    gridx = False, gridy = False,
    ndivisionsx = None,
    ndivisionsy = None,
    ndivisionsy_ratio = (5, 5, 0),
    stackdrawopt = "nostack",
    ratiodrawopt = "hist",
    legendpos = "UR",
    legendncol = 1,
    legendfillstyle = 0,
    legendfillcolor = 0,
    legendtextsize = 0.045,
    legendtitle = "",
    legendheightscale = 1.0,
    legendwidthscale = 1.0,
    CMSextraText = "Internal",
    lumiText = "Phase-2"
    ) :
    
    canvas = get_canvas(ratio = len(ratio_num_den_pairs))
    
    if (no_xerror) :
        
        ROOT.gStyle.SetErrorX(not no_xerror)
    
    canvas.cd(1)
    
    nentries = sum([(len(_obj.GetTitle()) > 0) for _obj in l_hist+l_hist_overlay+l_graph_overlay])
    legendHeight = legendheightscale * 0.065 * (nentries + 1.5*(len(legendtitle)>0))
    legendWidth = legendwidthscale * 0.4
    
    padTop = 1 - 0.3*canvas.GetTopMargin() - ROOT.gStyle.GetTickLength("y")
    padRight = 1 - canvas.GetRightMargin() - 0.6*ROOT.gStyle.GetTickLength("x")
    padBottom = canvas.GetBottomMargin() + 0.6*ROOT.gStyle.GetTickLength("y")
    padLeft = canvas.GetLeftMargin() + 0.6*ROOT.gStyle.GetTickLength("x")
    
    if(legendpos == "UR") :
        
        legend = ROOT.TLegend(padRight-legendWidth, padTop-legendHeight, padRight, padTop)
    
    elif(legendpos == "LR") :
        
        legend = ROOT.TLegend(padRight-legendWidth, padBottom, padRight, padBottom+legendHeight)
    
    elif(legendpos == "LL") :
        
        legend = ROOT.TLegend(padLeft, padBottom, padLeft+legendWidth, padBottom+legendHeight)
    
    elif(legendpos == "UL") :
        
        legend = ROOT.TLegend(padLeft, padTop-legendHeight, padLeft+legendWidth, padTop)
    
    else :
        
        print("Wrong legend position option:", legendpos)
        exit(1)
    
    
    legend.SetNColumns(legendncol)
    legend.SetFillStyle(legendfillstyle)
    legend.SetFillColor(legendfillcolor)
    legend.SetBorderSize(0)
    legend.SetHeader(legendtitle)
    legend.SetTextSize(legendtextsize)
    
    stack = ROOT.THStack()
    
    for hist in l_hist :
        
        hist.GetXaxis().SetRangeUser(xrange[0], xrange[1])
        #hist.SetFillStyle(0)
        
        #stack.Add(hist, "hist")
        stack.Add(hist, hist.GetOption())
        
        if (len(hist.GetTitle())) :
            
            #legend.AddEntry(hist, hist.GetTitle(), "F")#, "LP")
            legend.AddEntry(hist, hist.GetTitle(), get_draw_opt(hist))
    
    # Add a dummy histogram so that the X-axis range can be beyond the histogram range
    #h1_xRange = ROOT.TH1F("h1_xRange", "h1_xRange", 1, xrange[0], xrange[1])
    #stack.Add(h1_xRange)
    
    stack.Draw(stackdrawopt)
    
    if timeformatx :
        
        stack.GetXaxis().SetTimeDisplay(1)
        stack.GetXaxis().SetTimeFormat(timeformatx)
        stack.GetXaxis().SetTimeOffset(0, "gmt")
        stack.GetXaxis().SetLabelSize(0.04)
    
    stack.GetXaxis().SetRangeUser(xrange[0], xrange[1])
    stack.SetMinimum(yrange[0])
    stack.SetMaximum(yrange[1])
    
    if (len(l_hist_overlay)) :
        
        stack_overlay = ROOT.THStack()
        stack_overlay.SetName("stack_overlay")
        
        for hist in l_hist_overlay :
            
            #hist.Draw(f"same {hist.GetOption()}")
            #print(hist.GetOption())
            #print(hist.GetLineWidth())
            #print(hist.GetMarkerSize())
            #print(hist.GetMarkerStyle())
            stack_overlay.Add(hist, hist.GetOption())
            
            if (len(hist.GetTitle())) :
                
                #legend.AddEntry(hist, hist.GetTitle())#, hist.GetOption())#, "LPE")
                legend.AddEntry(hist, hist.GetTitle(), get_draw_opt(hist))#, hist.GetOption())#, "LPE")
        
        stack_overlay.Draw("nostack same")
        
        stack_overlay.GetXaxis().SetRangeUser(xrange[0], xrange[1])
        stack_overlay.SetMinimum(yrange[0])
        stack_overlay.SetMaximum(yrange[1])
    
    if (ndivisionsx is not None) :
        
        stack.GetXaxis().SetNdivisions(ndivisionsx[0], ndivisionsx[1], ndivisionsx[2], False)
    
    if (ndivisionsy is not None) :
        
        stack.GetYaxis().SetNdivisions(ndivisionsy[0], ndivisionsy[1], ndivisionsy[2], False)
    
    stack.GetXaxis().SetTitle(xtitle)
    #stack.GetXaxis().SetTitleSize(ROOT.gStyle.GetTitleSize("X") * xTitleSizeScale)
    #stack.GetXaxis().SetTitleOffset(ROOT.gStyle.GetTitleOffset("X") * 1.1)
    
    stack.GetYaxis().SetTitle(ytitle)
    stack.GetYaxis().SetTitleSize(0.055)
    #print(stack.GetYaxis().GetTitleSize())
    #stack.GetYaxis().SetTitleSize(ROOT.gStyle.GetTitleSize("Y") * yTitleSizeScale)
    stack.GetYaxis().SetTitleOffset(1)
    
    #stack.SetTitle(title)

    stack.GetXaxis().CenterTitle(centertitlex)
    stack.GetYaxis().CenterTitle(centertitley)
    
    stack.GetXaxis().CenterLabels(centerlabelx)
    stack.GetYaxis().CenterLabels(centerlabely)
    
    for gr in l_graph_overlay :
        
        #legend.AddEntry(gr, gr.GetTitle(), gr.GetHistogram().GetOption())
        legend.AddEntry(gr, gr.GetTitle(), get_draw_opt(gr))
        #gr.Draw(gr_overlay_drawopt)
        
        # ROOT<=6.30 does not have SetOption() for TGraph, hence GetOption() will not work
        gr.Draw(gr.GetHistogram().GetOption())
        #print(gr.GetHistogram().GetOption())
    
    legend.Draw()
    
    canvas.cd(1).SetLogx(logx)
    canvas.cd(1).SetLogy(logy)
    
    canvas.cd(1).SetGridx(gridx)
    canvas.cd(1).SetGridy(gridy)
    
    cms_lumi.lumiTextSize = 0.99
    cms_lumi.cmsTextSize = 0.99
    cms_lumi.relPosX = 0.045
    cms_lumi.CMS_lumi(pad = canvas.cd(1), iPeriod = 0, iPosX = 0, CMSextraText = CMSextraText, lumiText = lumiText)
    
    
    if (len(ratio_num_den_pairs)) :
        
        canvas.cd(2)
        
        stack_ratio = ROOT.THStack()
        
        l_gr_ratio_err = []
        
        for h1_num, h1_den in ratio_num_den_pairs :
            
            h1_ratio = h1_num.Clone()
            h1_ratio.GetXaxis().SetRangeUser(xrange[0], xrange[1])
            
            h1_ratio.Divide(h1_den)
            
            if (ratio_mode == "default") :
                
                pass
            
            elif (ratio_mode == "data") :
                
                gr_ratio_err = ROOT.TGraphAsymmErrors(h1_ratio.GetNbinsX())
                
                for ibin in range(0, h1_ratio.GetNbinsX()) :
                    
                    gr_ratio_err.SetPoint(ibin, h1_ratio.GetBinCenter(ibin+1), 1.0)
                    
                    if (h1_num.GetBinContent(ibin+1)) :
                        
                        print(h1_num.GetBinError(ibin+1), h1_num.GetBinContent(ibin+1), h1_num.GetBinError(ibin+1) / h1_num.GetBinContent(ibin+1))
                        h1_ratio.SetBinError(ibin+1, h1_ratio.GetBinContent(ibin+1) * h1_num.GetBinError(ibin+1) / h1_num.GetBinContent(ibin+1))
                    
                    if (h1_den.GetBinContent(ibin+1)) :
                        
                        ratio_err_upr = h1_den.GetBinError(ibin+1)/h1_den.GetBinContent(ibin+1)
                        ratio_err_lwr = h1_den.GetBinError(ibin+1)/h1_den.GetBinContent(ibin+1)
                        
                        gr_ratio_err.SetPointEYhigh(ibin, ratio_err_upr)
                        gr_ratio_err.SetPointEYlow(ibin, ratio_err_lwr)
                    
                    gr_ratio_err.SetPointEXhigh(ibin, h1_ratio.GetBinWidth(ibin+1) / 2.0)
                    gr_ratio_err.SetPointEXlow(ibin, h1_ratio.GetBinWidth(ibin+1) / 2.0)
                    
                    gr_ratio_err.SetFillColorAlpha(1, 1.0)
                    gr_ratio_err.SetFillStyle(3354)
                    gr_ratio_err.SetMarkerSize(0)
                    gr_ratio_err.SetLineWidth(0)
                
                #legend.AddEntry(gr_ratio_err, "error", "f")
                l_gr_ratio_err.append(gr_ratio_err)
            
            stack_ratio.Add(h1_ratio, ratiodrawopt)
        
        
        stack_ratio.Draw("nostack")
        
        stack_ratio.GetXaxis().SetRangeUser(xrange[0], xrange[1])
        stack_ratio.SetMinimum(yrange_ratio[0])
        stack_ratio.SetMaximum(yrange_ratio[1])
        
        if (ndivisionsx is not None) :
            
            stack_ratio.GetXaxis().SetNdivisions(ndivisionsx[0], ndivisionsx[1], ndivisionsx[2], False)
        
        if (ndivisionsy_ratio is not None) :
            
            stack_ratio.GetYaxis().SetNdivisions(ndivisionsy_ratio[0], ndivisionsy_ratio[1], ndivisionsy_ratio[2], False)
        
        stack_ratio.GetXaxis().CenterLabels(centerlabelx)
        stack_ratio.GetYaxis().CenterLabels(centerlabely)
        
        stack_ratio.GetXaxis().SetLabelSize(0.1)
        stack_ratio.GetYaxis().SetLabelSize(0.1)
        
        stack_ratio.GetXaxis().SetTitle(xtitle_ratio)
        stack_ratio.GetXaxis().SetTitleSize(0.13)
        stack_ratio.GetXaxis().SetTitleOffset(0.91)
        stack_ratio.GetXaxis().CenterTitle(centertitlex)
        
        stack_ratio.GetYaxis().SetTitle(ytitle_ratio)
        stack_ratio.GetYaxis().SetTitleSize(0.115)
        stack_ratio.GetYaxis().SetTitleOffset(0.45)
        stack_ratio.GetYaxis().CenterTitle(centertitley)
        
        for gr in l_gr_ratio_err :
            
            gr.Draw("E2")
        
        canvas.cd(2).SetGridx(gridx)
        canvas.cd(2).SetGridy(gridy)
    
    outdir = os.path.dirname(outfile)
    outfile_noext = os.path.splitext(outfile)[0]
    
    if (len(outdir)) :
        
        os.system(f"mkdir -p {outdir}")
    
    canvas.SaveAs(f"{outfile_noext}.pdf")
    #canvas.SaveAs(f"{outfile_noext}.png")
    pdf_to_png(infilename = f"{outfile_noext}.pdf")
    canvas.Close()
    
    return 0


def eval_category(rootfile, d_catcfgs, barcode = "") :
    
    d_cat_result = copy.deepcopy(d_catcfgs)
    
    d_read_info = {}
    d_fmt = d_cat_result["values"]
    
    for varkey, varname in d_cat_result["read"].items() :
        
        d_read_info[varkey] = rootfile.Get(varname)
        d_fmt[varkey] = f"d_read_info['{varkey}']"
    
    for metric, metric_str in d_cat_result["metrics"].items() :
        
        metric_str = metric_str.format(**d_fmt)
        d_cat_result["metrics"][metric] = eval(metric_str)
    
    cat = None
    
    for catname, cat_str in d_cat_result["categories"].items() :
        
        cat_str = cat_str.format(**{**d_cat_result["metrics"], **d_cat_result["categories"]})
        d_cat_result["categories"][catname] = eval(cat_str)
        
        if d_cat_result["categories"][catname] :
            
            cat = catname
    
    err = False
    
    if (cat is None) :
        
        err = True
        print(f"Error: module {barcode} category is invalid.")
    
    cat_sum = sum(list(d_cat_result["categories"].values()))
    
    if (cat_sum <= 0) :
        
        err = True
        print(f"Error: module {barcode} in uncategorized.")
    
    elif (cat_sum > 1) :
        
        err = True
        print(f"Error: module {barcode} uncategorization is not mutually exclusive.")
    
    if (err) :
        
        print(f"File: {rootfile.GetPath()}")
        print("Categorization:")
        yaml.dump(d_cat_result, sys.stdout)
        sys.exit(1)
    
    d_cat_result["category"] = cat
    
    return d_cat_result


def pdf_to_png(infilename, outfilename = None) :
    
    infname, _ = os.path.splitext(infilename)
    
    if (outfilename) :
        
        outfilename, _ = os.path.splitext(outfilename)
    
    else :
        
        outfilename = infname
    
    # .png is automatically added to the output file name
    retval = os.system(f"pdftoppm -cropbox -r 300 -png -singlefile {infilename} {outfilename}")
    
    return retval