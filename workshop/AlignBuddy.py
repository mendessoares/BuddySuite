#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Created on: Nov 18 2014 

"""
DESCRIPTION OF PROGRAM
AlignmentBuddy is a general wrapper for popular DNA and protein alignment programs that handles format conversion
and allows maintenance of rich feature annotation following alignment.
"""

# Standard library imports
import sys
import os
import zipfile
from copy import copy, deepcopy
from io import StringIO, TextIOWrapper
from random import sample
import re
from MyFuncs import TemporaryDirectory
from collections import OrderedDict
from shutil import *
from urllib import error, request
import subprocess
from fcntl import fcntl, F_SETFL

# Third party package imports
sys.path.insert(0, "./")  # For stand alone executable, where dependencies are packaged with BuddySuite
from Bio import AlignIO
from Bio.Align import MultipleSeqAlignment
from Bio.Align.AlignInfo import SummaryInfo
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.SeqFeature import SeqFeature
from Bio.SeqFeature import FeatureLocation
from Bio.Alphabet import IUPAC
from Bio.Data.CodonTable import TranslationError

# My functions

# ##################################################### WISH LIST #################################################### #
# - Map features from a sequence file over to the alignment
# - Back-translate


# ################################################# HELPER FUNCTIONS ################################################# #
class GuessError(Exception):
    """Raised when input format cannot be guessed"""
    def __init__(self, _value):
        self.value = _value

    def __str__(self):
        return self.value


def _stderr(message, quiet=False):
    if not quiet:
        sys.stderr.write(message)
    return


def _stdout(message, quiet=False):
    if not quiet:
        sys.stdout.write(message)
    return


def _get_seq_recs(_alignbuddy):
    seq_recs = []
    for _alignment in _alignbuddy.alignments:
        for _rec in _alignment:
            seq_recs.append(_rec)
    return seq_recs


def _make_copies(_alignbuddy):
    alphabet_list = [_rec.seq.alphabet for _rec in _get_seq_recs(_alignbuddy)]
    copies = deepcopy(_alignbuddy)
    copies.alpha = _alignbuddy.alpha
    for _indx, _rec in enumerate(_get_seq_recs(copies)):
        _rec.seq.alphabet = alphabet_list[_indx]
    return copies


def _format_to_extension(_format):
    format_to_extension = {'fasta': 'fa', 'fa': 'fa', 'genbank': 'gb', 'gb': 'gb', 'nexus': 'nex',
                           'nex': 'nex', 'phylip': 'phy', 'phy': 'phy', 'phylip-relaxed': 'phyr', 'phyr': 'phyr',
                           'stockholm': 'stklm', 'stklm': 'stklm'}
    return format_to_extension[_format]


def _get_alignment_binaries(_tool):
    tool_dict = {'mafft': 'http://mafft.cbrc.jp/alignment/software/',
                 'prank': 'http://wasabiapp.org/software/prank/prank_installation/',
                 'pagan': 'http://wasabiapp.org/software/pagan/pagan_installation/',
                 'muscle': 'http://www.drive5.com/muscle/downloads.htm',
                 'clustalw': 'http://www.clustal.org/clustal2/#Download',
                 'clustalomega': 'http://www.clustal.org/omega/#Download'}
    return tool_dict[_tool]

# ##################################################### Globals ###################################################### #
gap_characters = ["-", ".", " "]


# #################################################### ALIGN BUDDY ################################################### #
class AlignBuddy:  # Open a file or read a handle and parse, or convert raw into a Seq object
    def __init__(self, _input, _in_format=None, _out_format=None):
        # ####  IN AND OUT FORMATS  #### #
        # Holders for input type. Used for some error handling below
        in_handle = None
        raw_seq = None
        in_file = None

        # Handles
        if str(type(_input)) == "<class '_io.TextIOWrapper'>":
            if not _input.seekable():  # Deal with input streams (e.g., stdout pipes)
                temp = StringIO(_input.read())
                _input = temp
            _input.seek(0)
            in_handle = _input.read()
            _input.seek(0)

        # Plain text in a specific format
        if type(_input) == str and not os.path.isfile(_input):
            raw_seq = _input
            temp = StringIO(_input)
            _input = temp
            _input.seek(0)

        # File paths
        try:
            if os.path.isfile(_input):
                in_file = _input

        except TypeError:  # This happens when testing something other than a string.
            pass

        if not _in_format:
            self.in_format = guess_format(_input)
            self.out_format = str(self.in_format) if not _out_format else _out_format

        else:
            self.in_format = _in_format

        if not self.in_format:
            if in_file:
                raise GuessError("Could not determine format from _input file '{0}'.\n"
                                 "Try explicitly setting with -f flag.".format(in_file))
            elif raw_seq:
                raise GuessError("Could not determine format from raw input\n{0} ..."
                                 "Try explicitly setting with -f flag.".format(raw_seq)[:50])
            elif in_handle:
                raise GuessError("Could not determine format from input file-like object\n{0} ..."
                                 "Try explicitly setting with -f flag.".format(in_handle)[:50])
            else:  # This should be unreachable.
                raise GuessError("Unable to determine format or input type. Please check how SeqBuddy is being called.")

        self.out_format = self.in_format if not _out_format else _out_format

        # ####  ALIGNMENTS  #### #
        if type(_input) == AlignBuddy:
            _alignments = _input.alignments

        elif isinstance(_input, list):
            # make sure that the list is actually MultipleSeqAlignment objects
            _sample = _input if len(_input) < 5 else sample(_input, 5)
            for _seq in _sample:
                if type(_seq) != MultipleSeqAlignment:
                    raise TypeError("Seqlist is not populated with SeqRecords.")
            _alignments = _input

        elif str(type(_input)) == "<class '_io.TextIOWrapper'>" or isinstance(_input, StringIO):
            _alignments = list(AlignIO.parse(_input, self.in_format))

        elif os.path.isfile(_input):
            with open(_input, "r") as _input:
                _alignments = list(AlignIO.parse(_input, self.in_format))
        else:  # May be unreachable
            _alignments = None

        self.alpha = guess_alphabet(_alignments)
        for _alignment in _alignments:
            _alignment._alphabet = self.alpha
            for _seq in _alignment:
                _seq.seq.alphabet = self.alpha
        self.alignments = _alignments

    def print(self):
        print(self)
        return

    def __str__(self):
        if len(self.alignments) == 0:
            return "AlignBuddy object contains no alignments.\n"

        if self.out_format == "fasta" and len(self.alignments) > 1:
            raise ValueError("Error: FASTA format does not support multiple alignments in one file.\n")

        if self.out_format == "phylipi":
            _output = phylipi(self)

        elif self.out_format == "phylipis":
            _output = phylipi(self, "strict")

        else:
            tmp_dir = TemporaryDirectory()
            with open("%s/aligns.tmp" % tmp_dir.name, "w") as _ofile:
                AlignIO.write(self.alignments, _ofile, self.out_format)

            with open("%s/aligns.tmp" % tmp_dir.name, "r") as ifile:
                _output = ifile.read()

        return _output

    def write(self, _file_path):
        with open(_file_path, "w") as _ofile:
            _ofile.write("{0}\n".format(str(self).rstrip()))
        return


def guess_alphabet(_alignbuddy):
    _align_list = _alignbuddy if isinstance(_alignbuddy, list) else _alignbuddy.alignments
    _seq_list = []
    for _alignment in _align_list:
        _seq_list += [str(x.seq) for x in _alignment]

    _sequence = "".join(_seq_list).upper()
    _sequence = re.sub("[NX\-?]", "", _sequence)

    if len(_sequence) == 0:
        return None

    if 'U' in _sequence:  # U is unique to RNA
        return IUPAC.ambiguous_rna

    percent_dna = len(re.findall("[ATCG]", _sequence)) / float(len(_sequence))
    if percent_dna > 0.85:  # odds that a sequence with no Us and such a high ATCG count be anything but DNA is low
        return IUPAC.ambiguous_dna
    else:
        return IUPAC.protein


def guess_format(_input):  # _input can be list, SeqBuddy object, file handle, or file path.
    # If input is just a list, there is no BioPython in-format. Default to gb.
    if isinstance(_input, list):
        return "stockholm"

    # Pull value directly from object if appropriate
    if type(_input) == AlignBuddy:
        return _input.in_format

    # If input is a handle or path, try to read the file in each format, and assume success if not error and # seqs > 0
    if os.path.isfile(str(_input)):
        _input = open(_input, "r")

    if str(type(_input)) == "<class '_io.TextIOWrapper'>" or isinstance(_input, StringIO):
        # Die if file is empty
        if _input.read() == "":
            sys.exit("Input file is empty.")
        _input.seek(0)

        possible_formats = ["gb", "phylip-relaxed", "stockholm", "fasta", "nexus", "clustal", "pir"]
        for _format in possible_formats:
            try:
                _input.seek(0)
                _alignments = AlignIO.parse(_input, _format)
                if next(_alignments):
                    _input.seek(0)
                    return _format
                else:
                    continue
            except StopIteration:  # ToDo check that other types of error are not possible
                continue
            except ValueError:
                continue
        return None  # Unable to determine format from file handle

    else:
        raise GuessError("Unsupported _input argument in guess_format(). %s" % _input)


def phylipi(_alignbuddy, _format="relaxed"):  # _format in ["strict", "relaxed"]
    _output = ""
    for _alignment in _alignbuddy.alignments:
        max_id_length = 0
        max_seq_length = 0
        for _rec in _alignment:
            max_id_length = len(_rec.id) if len(_rec.id) > max_id_length else max_id_length
            max_seq_length = len(_rec.seq) if len(_rec.seq) > max_seq_length else max_seq_length

        _output += " %s %s\n" % (len(_alignment), max_seq_length)
        for _rec in _alignment:
            _seq_id = _rec.id.ljust(max_id_length) if _format == "relaxed" else _rec.id[:10].ljust(10)
            _output += "%s  %s\n" % (_seq_id, _rec.seq)
        _output += "\n"
    return _output


# #################################################################################################################### #
def list_ids(_alignbuddy):
    _output = []
    for al_indx, _alignment in enumerate(_alignbuddy.alignments):
        _output.append([])
        for _rec in _alignment:
            _output[al_indx].append(_rec.id)
    return _output


def num_seqs(_alignbuddy):
    return [len(_alignment) for _alignment in _alignbuddy.alignments]


def uppercase(_alignbuddy):
    for _rec in _get_seq_recs(_alignbuddy):
        _rec.seq = Seq(str(_rec.seq).upper(), alphabet=_rec.seq.alphabet)
    return _alignbuddy


def lowercase(_alignbuddy):
    for _rec in _get_seq_recs(_alignbuddy):
        _rec.seq = Seq(str(_rec.seq).lower(), alphabet=_rec.seq.alphabet)
    return _alignbuddy


def clean_seq(_alignbuddy, skip_list=None):
    """remove all non-sequence charcters from sequence strings"""
    skip_list = "" if not skip_list else "".join(skip_list)
    for _rec in _get_seq_recs(_alignbuddy):
        if _alignbuddy.alpha == IUPAC.protein:
            _rec.seq = Seq(re.sub("[^ACDEFGHIKLMNPQRSTVWXYacdefghiklmnpqrstvwxy%s]" % skip_list, "", str(_rec.seq)),
                           alphabet=_alignbuddy.alpha)
        else:
            _rec.seq = Seq(re.sub("[^ATGCUatgcu%s]" % skip_list, "", str(_rec.seq)), alphabet=_alignbuddy.alpha)

    return _alignbuddy


def codon_alignment(_alignbuddy):
    if _alignbuddy.alpha == IUPAC.protein:
        raise TypeError("Nucleic acid sequence required, not protein.")

    for _rec in _get_seq_recs(_alignbuddy):
        if _rec.seq.alphabet == IUPAC.protein:
            raise TypeError("Error: Record %s is protein. Nucleic acid required." % _rec.name)

        seq_string = str(_rec.seq)
        _output = seq_string[0]
        held_residues = ""
        position = 2
        for _residue in seq_string[1:]:
            if position == 1:
                while len(held_residues) >= 3:
                    _output += held_residues[:3]
                    held_residues = held_residues[3:]
                position = len(held_residues) + 1
                _output += held_residues
                held_residues = ""

            if position == 1:
                _output += _residue

            elif _output[-1] not in gap_characters and _residue not in gap_characters:
                _output += _residue

            elif _output[-1] in gap_characters and _residue in gap_characters:
                _output += _residue

            else:
                held_residues += _residue
                continue

            if position != 3:
                position += 1
            else:
                position = 1

        _output += held_residues
        _rec.seq = Seq(_output, alphabet=_rec.seq.alphabet)

    return _alignbuddy


def translate_cds(_alignbuddy, quiet=False):  # adding 'quiet' will suppress the errors thrown by translate(cds=True)
    if _alignbuddy.alpha == IUPAC.protein:
        raise TypeError("Nucleic acid sequence required, not protein.")

    def trans(in_seq):
        try:
            in_seq.seq = in_seq.seq.translate(cds=True, to_stop=True)
            return in_seq

        except TranslationError as _e1:
            if not quiet:
                sys.stderr.write("Warning: %s in %s\n" % (_e1, in_seq.id))
            return _e1

    def map_gaps(nucl, pep):
        nucl = str(nucl.seq)
        pep_string = str(pep.seq)
        new_seq = ""
        for _codon in [nucl[i:i + 3] for i in range(0, len(nucl), 3)]:
            if _codon[0] not in gap_characters:
                new_seq += pep_string[0]
                pep_string = pep_string[1:]

            else:
                new_seq += "-"
        pep.seq = Seq(new_seq, alphabet=IUPAC.protein)
        return pep

    codon_alignment(_alignbuddy)
    copy_alignbuddy = _make_copies(_alignbuddy)
    clean_seq(copy_alignbuddy, skip_list="RYWSMKHBVDNXrywsmkhbvdnx")
    for align_indx, _alignment in enumerate(copy_alignbuddy.alignments):
        for rec_indx, _rec in enumerate(_alignment):
            _rec.features = []
            while True:
                test_trans = trans(copy(_rec))
                # success
                if str(type(test_trans)) == "<class 'Bio.SeqRecord.SeqRecord'>":
                    break

                # not standard length
                if re.search("Sequence length [0-9]+ is not a multiple of three", str(test_trans)):
                    orig_rec = _alignbuddy.alignments[align_indx][rec_indx]
                    orig_rec_seq = str(orig_rec.seq)
                    for _ in range(len(str(_rec.seq)) % 3):
                        orig_rec_seq = re.sub(".([%s]+)$" % "".join(gap_characters), r"\1-", orig_rec_seq)

                    orig_rec.seq = Seq(orig_rec_seq, alphabet=orig_rec.seq.alphabet)

                    _rec.seq = Seq(str(_rec.seq)[:(len(str(_rec.seq)) - len(str(_rec.seq)) % 3)],
                                   alphabet=_rec.seq.alphabet)
                    continue

                # not a start codon
                if re.search("First codon '[A-Za-z]{3}' is not a start codon", str(test_trans)):
                    _rec.seq = Seq("ATG" + str(_rec.seq)[3:], alphabet=_rec.seq.alphabet)
                    continue

                # not a stop codon
                if re.search("Final codon '[A-Za-z]{3}' is not a stop codon", str(test_trans)):
                    _rec.seq = Seq(str(_rec.seq) + "TGA", alphabet=_rec.seq.alphabet)
                    continue

                # non-standard characters
                if re.search("Codon '[A-Za-z]{3}' is invalid", str(test_trans)):
                    regex = re.findall("Codon '([A-Za-z]{3})' is invalid", str(test_trans))
                    regex = "(?i)%s" % regex[0]
                    _rec.seq = Seq(re.sub(regex, "NNN", str(_rec.seq), count=1), alphabet=_rec.seq.alphabet)
                    continue

                # internal stop codon(s) found
                if re.search("Extra in frame stop codon found", str(test_trans)):
                    for _i in range(round(len(str(_rec.seq)) / 3) - 1):
                        codon = str(_rec.seq)[(_i * 3):(_i * 3 + 3)]
                        if codon.upper() in ["TGA", "TAG", "TAA"]:
                            stop_removed = str(_rec.seq)[:(_i * 3)] + "NNN" + str(_rec.seq)[(_i * 3 + 3):]
                            _rec.seq = Seq(stop_removed, alphabet=_rec.seq.alphabet)
                    continue

                break  # Safety valve, should be unreachable

            try:
                _rec.seq = _rec.seq.translate()
                _rec.seq.alphabet = IUPAC.protein
                _rec = map_gaps(_alignbuddy.alignments[align_indx][rec_indx], _rec)
                _alignbuddy.alignments[align_indx][rec_indx].seq = Seq(str(_rec.seq), alphabet=_rec.seq.alphabet)

            except TranslationError as e1:  # Should be unreachable
                raise TranslationError("%s failed to translate  --> %s\n" % (_rec.id, e1))

    _alignbuddy.alpha = IUPAC.protein
    return _alignbuddy


def delete_rows(_alignbuddy, _search):
    _alignments = []
    for _alignment in _alignbuddy.alignments:
        matches = []
        for record in _alignment:
            if not re.search(_search, record.id) and not re.search(_search, record.description) \
                    and not re.search(_search, record.name):
                matches.append(record)
        _alignments.append(MultipleSeqAlignment(matches))
    _alignbuddy.alignments = _alignments
    trimal(_alignbuddy, "clean")
    return _alignbuddy


def pull_rows(_alignbuddy, _search):
    _alignments = []
    for _alignment in _alignbuddy.alignments:
        matches = []
        for record in _alignment:
            if re.search(_search, record.id) or re.search(_search, record.description) \
                    or re.search(_search, record.name):
                matches.append(record)
        _alignments.append(MultipleSeqAlignment(matches))
    _alignbuddy.alignments = _alignments
    trimal(_alignbuddy, "clean")
    return _alignbuddy


# http://trimal.cgenomics.org/_media/manual.b.pdf
# ftp://trimal.cgenomics.org/trimal/
def trimal(_alignbuddy, _threshold, _window_size=1):  # This is broken, not sure why
    for alignment_index, _alignment in enumerate(_alignbuddy.alignments):

        # gap_distr is the number of columns w/ each possible number of gaps; the index is == to number of gaps
        gap_distr = [0 for _ in range(len(_alignment) + 1)]
        num_columns = _alignment.get_alignment_length()
        each_column = [0 for _ in range(num_columns)]

        max_gaps = 0

        for _indx in range(num_columns):
                num_gaps = len(re.findall("-", str(_alignment[:, _indx])))
                gap_distr[num_gaps] += 1
                each_column[_indx] = num_gaps

        def res_sim_score():
            return

        def remove_cols(cuts):
            _new_alignment = _alignment[:, 0:0]
            for _col in cuts:
                _new_alignment += _alignment[:, _col:_col + 1]
            return _new_alignment

        def gappyout():
            for i in gap_distr:
                if i == 0:
                    max_gaps = i + 1
                else:
                    break

            max_slope = -1
            slopes = [-1 for _ in range(len(_alignment) + 1)]
            max_iter = len(_alignment) + 1
            active_pointer = 0
            while active_pointer < max_iter:
                for i in gap_distr:
                    if i == 0:
                        active_pointer += 1
                    else:
                        break

                prev_pointer1 = int(active_pointer)
                if active_pointer + 1 >= max_iter:
                    break

                while True:
                    active_pointer += 1
                    if active_pointer + 1 >= max_iter or gap_distr[active_pointer] != 0:
                        break

                prev_pointer2 = int(active_pointer)
                if active_pointer + 1 >= max_iter:
                    break

                while True:
                    active_pointer += 1
                    if active_pointer + 1 >= max_iter or gap_distr[active_pointer] != 0:
                        break

                if active_pointer + 1 >= max_iter:
                    break

                slopes[active_pointer] = (active_pointer - prev_pointer2) / len(_alignment)
                slopes[active_pointer] /= (gap_distr[active_pointer] + gap_distr[prev_pointer2]) / num_columns

                if slopes[prev_pointer1] != -1:
                    if slopes[active_pointer] / slopes[prev_pointer1] > max_slope:
                        max_slope = slopes[active_pointer] / slopes[prev_pointer1]
                        max_gaps = prev_pointer1
                elif slopes[prev_pointer2] != -1:
                    if slopes[active_pointer] / slopes[prev_pointer2] > max_slope:
                        max_slope = slopes[active_pointer] / slopes[prev_pointer2]
                        max_gaps = prev_pointer1

                active_pointer = prev_pointer2

            def mark_cuts():
                cuts = []
                for _col, _gaps in enumerate(each_column):
                    if _gaps <= max_gaps:
                        cuts.append(_col)
                return cuts

            return remove_cols(mark_cuts())

        def strict():
            return

        if _threshold in ["no_gaps", "all"]:
            _threshold = 0
            new_alignment = _alignment[:, 0:0]
            for _col, _gaps in enumerate(each_column):
                if _gaps <= max_gaps:
                    new_alignment += _alignment[:, _col:_col + 1]

        if _threshold == "clean":
            max_gaps = len(_alignment) - 1
            new_alignment = _alignment[:, 0:0]
            for _col, _gaps in enumerate(each_column):
                if _gaps <= max_gaps:
                    new_alignment += _alignment[:, _col:_col + 1]

        elif _threshold == "gappyout":
            new_alignment = gappyout()

        elif _threshold == "strict":

            pass
        elif _threshold == "strictplus":
            pass
        else:
            try:
                if _threshold == 1:
                    _stderr("Warning: Ambiguous threshold of '1'. Assuming 100%, use 0.01 for 1%")

                _threshold = float(_threshold)
                _threshold = 0.0001 if _threshold == 0 else _threshold
                _threshold = (_threshold / 100) if _threshold > 1 else _threshold  # Allows percent or fraction

                max_gaps = round(len(_alignment) * _threshold)

                new_alignment = _alignment[:, 0:0]
                for _col, _gaps in enumerate(each_column):
                    if _gaps <= max_gaps:
                        new_alignment += _alignment[:, _col:_col + 1]

            except ValueError:
                raise ValueError("Unable to understand the threshold parameter provided -> %s)" % _threshold)

        _alignbuddy.alignments[alignment_index] = new_alignment

    return _alignbuddy


def consensus_sequence(_alignbuddy):
    # http://bioinformatics.oxfordjournals.org/content/18/11/1494
    _output = []
    for _alignment in _alignbuddy.alignments:
        _id = _alignment[0].id
        aln = SummaryInfo(_alignment)
        print(aln.gap_consensus())
        _output.append(SeqRecord(seq=aln.gap_consensus(), id=_id))
    return _output


def concat_alignments(_alignbuddy, _pattern):
    # collapsed multiple genes from single taxa down to one consensus seq
    # detected mixed sequence types
    if len(_alignbuddy.alignments) < 2:
        raise AttributeError("Please provide ")

    def organism_list():
        orgnsms = set()
        for _align in _alignbuddy.alignments:
            for _record in _align:
                orgnsms.add(_record.id)
        return list(orgnsms)

    def add_blanks(_record, _num):
        for _ in range(_num):
            _record.seq += '-'

    missing_organisms = organism_list()

    # dict[alignment_index][organism] -> gene_name
    sequence_names = OrderedDict()
    for al_indx, _alignment in enumerate(_alignbuddy.alignments):
        sequence_names[al_indx] = OrderedDict()
        for record in _alignment:
            organism = re.split(_pattern, record.id)[0]
            gene = ''.join(re.split(_pattern, record.id)[1:])
            if organism in sequence_names[al_indx].keys():
                sequence_names[al_indx][organism].append(gene)
            else:
                sequence_names[al_indx][organism] = [gene]
            record.id = organism
    for al_indx, _alignment in enumerate(_alignbuddy.alignments):
        duplicate_table = OrderedDict()
        for record in _alignment:
            if record.id in duplicate_table.keys():
                duplicate_table[record.id].append(record)
            else:
                duplicate_table[record.id] = [record]
        _temp = []
        for record in _alignment:
            if len(duplicate_table[record.id]) == 1:
                _temp.append(record)
                duplicate_table.pop(record.id)
        _alignbuddy.alignments[al_indx] = MultipleSeqAlignment(_temp, alphabet=_alignbuddy.alpha)
        for gene in duplicate_table:
            consensus = SummaryInfo(MultipleSeqAlignment(duplicate_table[gene]))
            consensus = consensus.gap_consensus(consensus_alpha=_alignbuddy.alpha)
            consensus = SeqRecord(seq=consensus, id=gene)
            _alignbuddy.alignments[al_indx].append(consensus)

    for al_indx in range(len(_alignbuddy.alignments)):
        for _id in missing_organisms:
            organism = re.split(_pattern, _id)[0]
            if organism not in sequence_names[al_indx].keys():
                sequence_names[al_indx][organism] = ['missing']

    for x in range(len(missing_organisms)):
        missing_organisms[x] = re.split(_pattern, missing_organisms[x])[0]

    base_alignment = deepcopy(_alignbuddy.alignments[0])
    for record in base_alignment:
        while record.id in missing_organisms:
            missing_organisms.remove(record.id)
    for organism in missing_organisms:
        new_record = SeqRecord(Seq('', alphabet=_alignbuddy.alpha), id=re.split(_pattern, organism)[0])
        add_blanks(new_record, base_alignment.get_alignment_length())
        base_alignment.append(new_record)

    for record in base_alignment:
        record.description = 'concatenated_alignments'
        record.name = 'multiple'

    curr_length = 0
    for al_indx, _alignment in enumerate(_alignbuddy.alignments):
        for base_indx, base_rec in enumerate(base_alignment):
            added = False
            for record in _alignment:
                if base_rec.id == record.id:
                    if al_indx > 0:
                        base_rec.seq += record.seq
                        added = True
            if not added and al_indx > 0:
                add_blanks(base_rec, _alignment.get_alignment_length())
            feature_location = FeatureLocation(start=curr_length,
                                               end=curr_length + _alignment.get_alignment_length())
            feature = SeqFeature(location=feature_location, type='alignment' + str(al_indx + 1),
                                 qualifiers={'name': sequence_names[al_indx][base_rec.id]})
            base_alignment[base_indx].features.append(feature)
        curr_length += _alignment.get_alignment_length()

    _alignbuddy.alignments = [base_alignment]
    return _alignbuddy


def rename(_alignbuddy, query, replace="", _num=0):  # TODO Allow a replacement pattern increment (like numbers)
    for _alignment in _alignbuddy.alignments:
        for _rec in _alignment:
            new_name = re.sub(query, replace, _rec.id, _num)
            _rec.id = new_name
            _rec.name = new_name
    return _alignbuddy


def order_ids(_alignbuddy, _reverse=False):
    for al_indx, _alignment in enumerate(_alignbuddy.alignments):
        _output = [(_rec.id, _rec) for _rec in _alignment]
        _output = sorted(_output, key=lambda x: x[0], reverse=_reverse)
        _output = [_rec[1] for _rec in _output]
        _alignbuddy.alignments[al_indx] = MultipleSeqAlignment(_output)
    return _alignbuddy


def rna2dna(_alignbuddy):
    if _alignbuddy.alpha == IUPAC.protein:
        raise TypeError("Nucleic acid sequence required, not protein.")
    for _alignment in _alignbuddy.alignments:
        for _rec in _alignment:
            _rec.seq = Seq(str(_rec.seq.back_transcribe()), alphabet=IUPAC.ambiguous_dna)
    _alignbuddy.alpha = IUPAC.ambiguous_dna
    return _alignbuddy


def dna2rna(_alignbuddy):
    if _alignbuddy.alpha == IUPAC.protein:
        raise TypeError("Nucleic acid sequence required, not protein.")
    for _alignment in _alignbuddy.alignments:
        for _rec in _alignment:
            _rec.seq = Seq(str(_rec.seq.transcribe()), alphabet=IUPAC.ambiguous_rna)
    _alignbuddy.alpha = IUPAC.ambiguous_rna
    return _alignbuddy


def extract_range(_alignbuddy, _start, _end):
    _start = 1 if int(_start) < 1 else _start
    # Don't use the standard index-starts-at-0... _end must be left for the range to be inclusive
    _start, _end = int(_start) - 1, int(_end)
    if _end < _start:
        raise ValueError("Error at extract range: The value given for end of range is smaller than for the start "
                         "of range.")
    for _alignment in _alignbuddy.alignments:
        for _rec in _alignment:
            _rec.seq = Seq(str(_rec.seq)[_start:_end], alphabet=_rec.seq.alphabet)
            _rec.description += " Sub-sequence extraction, from residue %s to %s" % (_start + 1, _end)
            _features = []
            for _feature in _rec.features:
                if _feature.location.end < _start:
                    continue
                if _feature.location.start > _end:
                    continue

                feat_start = _feature.location.start - _start
                if feat_start < 0:
                    feat_start = 0

                feat_end = _feature.location.end - _start
                if feat_end > len(str(_rec.seq)):
                    feat_end = len(str(_rec.seq))

                new_location = FeatureLocation(feat_start, feat_end)
                _feature.location = new_location
                _features.append(_feature)
            _rec.features = _features
    return _alignbuddy


def alignment_lengths(_alignbuddy):
    _output = []
    for _alignment in _alignbuddy.alignments:
        _output.append(_alignment.get_alignment_length())
    return _output


def split_alignbuddy(_alignbuddy):
    ab_objs_list = []
    for _alignment in _alignbuddy.alignments:
        _ab = AlignBuddy([_alignment])
        _ab.in_format = _alignbuddy.in_format
        _ab.out_format = _alignbuddy.out_format
        ab_objs_list.append(_ab)
    return ab_objs_list


def generate_msa(_seqbuddy, _tool, _params):
    if _params is None:
        _params = ''
    _tool = _tool.lower()
    if _tool not in ['pagan', 'prank', 'muscle', 'clustalw', 'clustalomega', 'mafft']:
        raise AttributeError("{0} is not a valid alignment tool.".format(_tool))
    if which(_tool) is None:
        _stderr('#### Could not find {0} in $PATH. ####\n'.format(_tool), in_args.quiet)
        _stderr('Please go to {0} to install {1}.\n'.format(_get_alignment_binaries(_tool),_tool))
        sys.exit()
    else:
        tmp_dir = TemporaryDirectory()
        with open("{0}/tmp.fa".format(tmp_dir.name), 'w') as out_file:
            out_file.write(str(_seqbuddy))
        command = '{0} {1} {2}'.format(_tool, ''.join(_params), "{0}/tmp.fa".format(tmp_dir.name))
        try:
            _output = subprocess.check_output(command, shell=True, universal_newlines=True)
        except subprocess.CalledProcessError:
            _stderr('\n#### {0} threw an error. Scroll up for more info. ####\n\n'.format(_tool), in_args.quiet)
            sys.exit()
        if _tool == 'mafft' and '--clustalout' in _params:  # MAFFT adds extra spaces to clustal in v7.245 (2015/07/22)
            contents = ''
            prev_line = ''
            for line in _output.splitlines(keepends=True):
                if line.startswith(' ') and len(line) == len(prev_line) + 1:
                    contents += line[1:]
                else:
                    contents += line
                prev_line = line
            _output = contents
        _alignbuddy = AlignBuddy(_output)
        return _alignbuddy


# ################################################# COMMAND LINE UI ################################################## #
if __name__ == '__main__':
    import argparse
    if '--params' in sys.argv:
        sys.argv[sys.argv.index('--params')] = '-p'
    if '-p' in sys.argv:
        arg_index = sys.argv.index('-p')
        _params = '-p' + sys.argv.pop(arg_index+1)
        sys.argv[arg_index] = _params

    parser = argparse.ArgumentParser(prog="alignBuddy", description="Sequience alignment with a splash of Kava")
    parser.add_argument("alignment", help="The file(s) you want to start working on", nargs="*", default=[sys.stdin])
    parser.add_argument('-v', '--version', action='version',
                        version='''\
AlignBuddy 1.alpha (2015)

Gnu General Public License, Version 2.0 (http://www.gnu.org/licenses/gpl.html)
This is free software; see the source for detailed copying conditions.
There is NO warranty; not even for MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE.
Questions/comments/concerns can be directed to Steve Bond, steve.bond@nih.gov''')

    parser.add_argument('-cs', '--clean_seq', action='append', nargs="?",
                        help="Strip out non-sequence characters, such as stops (*) and gaps (-). Pass in the word "
                             "'strict' to remove all characters except the unambiguous letter codes.")
    parser.add_argument('-uc', '--uppercase', action='store_true', help='Convert all sequences to uppercase')
    parser.add_argument('-lc', '--lowercase', action='store_true', help='Convert all sequences to lowercase')
    parser.add_argument('-tr', '--translate', action='store_true',
                        help="Convert coding sequences into amino acid sequences")
    parser.add_argument('-an', '--features', action="store_true")  # ToDo: Delete
    parser.add_argument('-li', '--list_ids', nargs='?', action='append', type=int, metavar='int (optional)',
                        help="Output all the sequence identifiers in a file. Optionally, pass in an integer to "
                             "specify the # of columns to write")
    parser.add_argument('-ns', '--num_seqs', action='store_true',
                        help="Counts how many sequences are present in each alignment")
    parser.add_argument('-sf', '--screw_formats', action='store', help="Arguments: <out_format>")
    parser.add_argument('-ca', '--codon_alignment', action='store_true',
                        help="Shift all gaps so the sequence is in triplets.")
    parser.add_argument('-dr', '--delete_rows', action='store',
                        help="Remove selected rows from alignments. Arguments: <search_pattern>")
    parser.add_argument('-pr', '--pull_rows', action='store',
                        help="Keep selected rows from alignements. Arguments: <search_pattern>")
    parser.add_argument('-trm', '--trimal', nargs='?', action='append',
                        help="Delete columns with a certain percentage of gaps. Or auto-detect with 'gappyout'.")
    parser.add_argument('-cta', '--concat_alignments', action='store',
                        help="Concatenates two or more alignments by splitting and matching the sequence identifiers."
                             " Arguments: <split_pattern>")
    parser.add_argument('-ri', '--rename_ids', action='store', metavar=('<pattern>', '<substitution>'), nargs=2,
                        help="Replace some pattern in ids with something else. Limit number of replacements with -p.")
    parser.add_argument('-oi', '--order_ids', action='append', nargs="?",
                        help="Sort all sequences in an alignment by id in alpha-numeric order. "
                             "Pass in the word 'rev' to reverse order")
    parser.add_argument('-d2r', '--transcribe', action='store_true',
                        help="Convert DNA alignments to RNA")
    parser.add_argument('-r2d', '--back_transcribe', action='store_true',
                        help="Convert RNA alignments to DNA")
    parser.add_argument('-er', '--extract_range', action='store', nargs=2, metavar=("<start (int)>", "<end (int)>"),
                        type=int, help="Pull out sub-alignments in a given range.")
    parser.add_argument('-al', '--alignment_lengths', action='store_true', help="Returns a list of alignment lengths.")
    parser.add_argument("-stf", "--split_to_files", action='store', nargs=2, metavar=("<out dir>", "<out file>"),
                        help="Write individual files for each alignment")
    parser.add_argument("-ga", "--generate_alignment", action='append')

    parser.add_argument("-i", "--in_place", help="Rewrite the input file in-place. Be careful!", action='store_true')
    parser.add_argument('-p', '--params', help="Free form arguments for some functions", action='store')
    parser.add_argument('-q', '--quiet', help="Suppress stderr messages", action='store_true')
    parser.add_argument('-t', '--test', action='store_true',
                        help="Run the function and return any stderr/stdout other than sequences.")
    parser.add_argument('-o', '--out_format', help="Some functions use this flag for output format", action='store')
    parser.add_argument('-f', '--in_format', action='store',
                        help="If AlignBuddy can't guess the file format, just specify it directly.")
    in_args = parser.parse_args()

    alignbuddy = []
    align_set = ""

    # Generate Alignment
    if in_args.generate_alignment:
        import SeqBuddy as Sb
        seqbuddy = []
        for seq_set in in_args.alignment:
            if isinstance(seq_set, TextIOWrapper) and seq_set.buffer.raw.isatty():
                sys.exit("Warning: No input detected. Process will be aborted.")
            seq_set = Sb.SeqBuddy(seq_set, in_args.in_format, in_args.out_format)
            seqbuddy += seq_set.records
        seqbuddy = Sb.SeqBuddy(seqbuddy, seq_set.in_format, seq_set.out_format)
        _stdout(str(generate_msa(seqbuddy, in_args.generate_alignment[0], in_args.params)))
        sys.exit()

    for align_set in in_args.alignment:
        if isinstance(align_set, TextIOWrapper) and align_set.buffer.raw.isatty():
                sys.exit("Warning: No input detected. Process will be aborted.")
        align_set = AlignBuddy(align_set, in_args.in_format, in_args.out_format)
        alignbuddy += align_set.alignments

    alignbuddy = AlignBuddy(alignbuddy, align_set.in_format, align_set.out_format)

    # ############################################# INTERNAL FUNCTIONS ############################################## #
    def _print_aligments(_alignbuddy):
        try:
            _output = str(_alignbuddy)
        except ValueError as e:
            _stderr("Error: %s\n" % str(e))
            return False
        except TypeError as e:
            _stderr("Error: %s\n" % str(e))
            return False

        if in_args.test:
            _stderr("*** Test passed ***\n", in_args.quiet)
            pass

        elif in_args.in_place:
            _in_place(_output, in_args.alignment[0])

        else:
            _stdout("{0}\n".format(_output.rstrip()))
        return True


    def _in_place(_output, _path):
        if not os.path.exists(_path):
            _stderr("Warning: The -i flag was passed in, but the positional argument doesn't seem to be a "
                    "file. Nothing was written.\n", in_args.quiet)
            _stderr("%s\n" % _output.rstrip(), in_args.quiet)
        else:
            with open(os.path.abspath(_path), "w") as _ofile:
                _ofile.write(_output)
            _stderr("File over-written at:\n%s\n" % os.path.abspath(_path), in_args.quiet)

    # ############################################## COMMAND LINE LOGIC ############################################## #
    # Screw formats
    if in_args.screw_formats:
        alignbuddy.out_format = in_args.screw_formats
        _print_aligments(alignbuddy)

    # List identifiers
    if in_args.list_ids:
        columns = 1 if not in_args.list_ids[0] or in_args.list_ids == 0 else abs(in_args.list_ids[0])
        listed_ids = list_ids(alignbuddy)
        output = ""
        for indx, alignment in enumerate(listed_ids):
            count = 1
            output += "# Alignment %s\n" % str(indx + 1)
            for identifier in alignment:
                if count < columns:
                    output += "%s\t" % identifier
                    count += 1
                else:
                    output += "%s\n" % identifier
                    count = 1
            output += "\n"
        _stdout(output)

    # Number sequences per alignment
    if in_args.num_seqs:
        counts = num_seqs(alignbuddy)
        output = ""
        for indx, count in enumerate(counts):
            output += "# Alignment %s\n%s\n\n" % (indx + 1, count) if len(counts) > 1 else "%s\n" % count

        _stdout("%s\n" % output.strip())

    # Clean Seq
    if in_args.clean_seq:
        if in_args.clean_seq[0] == "strict":
            _print_aligments(clean_seq(alignbuddy))
        else:
            _print_aligments(clean_seq(alignbuddy, skip_list="RYWSMKHBVDNXrywsmkhbvdnx"))

    # Uppercase
    if in_args.uppercase:
        _print_aligments(uppercase(alignbuddy))

    # Lowercase
    if in_args.lowercase:
        _print_aligments(lowercase(alignbuddy))

    # This is temporary for testing purposes
    if in_args.features:
        blahh = ['annotations', 'dbxrefs', 'description', 'features', 'id', 'letter_annotations', 'name', 'seq']
        foo = alignbuddy.alignments[0][0]
        bar = [foo.annotations, foo.dbxrefs, foo.description, foo.features, foo.id, foo.letter_annotations, foo.name, foo.seq]
        for indx, value in enumerate(blahh):
            print("{0}: {1}".format(value, bar[indx]))
        print("\nannotations{0}: ".format(alignbuddy.alignments[0].annotations))

    # Codon alignment
    if in_args.codon_alignment:
        _print_aligments(codon_alignment(alignbuddy))

    # Translate CDS
    if in_args.translate:
        _print_aligments(translate_cds(alignbuddy, quiet=in_args.quiet))

    # Pull rows
    if in_args.pull_rows:
        _print_aligments(pull_rows(alignbuddy, in_args.pull_rows))

    # Delete rows
    if in_args.delete_rows:
        _print_aligments(delete_rows(alignbuddy, in_args.delete_rows))

    # Trimal
    if in_args.trimal:
        in_args.trimal = 1.0 if not in_args.trimal[0] else in_args.trimal[0]
        _print_aligments(trimal(alignbuddy, in_args.trimal))

    # Concatenate Alignments
    if in_args.concat_alignments:
        _print_aligments(concat_alignments(alignbuddy, in_args.concat_alignments))

    # Rename IDs
    if in_args.rename_ids:
        num = 0 if not in_args.params else int(in_args.params[0])
        _print_aligments(rename(alignbuddy, in_args.rename_ids[0], in_args.rename_ids[1], num))

    # Order IDs
    if in_args.order_ids:
        reverse = True if in_args.order_ids[0] and in_args.order_ids[0] == "rev" else False
        _print_aligments(order_ids(alignbuddy, _reverse=reverse))

    # Transcribe
    if in_args.transcribe:
        if alignbuddy.alpha != IUPAC.ambiguous_dna:
            raise ValueError("You need to provide a DNA sequence.")
        _print_aligments(dna2rna(alignbuddy))

    # Back Transcribe
    if in_args.back_transcribe:
        if alignbuddy.alpha != IUPAC.ambiguous_rna:
            raise ValueError("You need to provide an RNA sequence.")
        _print_aligments(rna2dna(alignbuddy))

    # Extract range
    if in_args.extract_range:
        _print_aligments(extract_range(alignbuddy, *in_args.extract_range))

    # Alignment lengths
    if in_args.alignment_lengths:
        counts = alignment_lengths(alignbuddy)
        output = ""
        for indx, count in enumerate(counts):
            output += "# Alignment %s\n%s\n\n" % (indx + 1, count) if len(counts) > 1 else "%s\n" % count

        _stdout("%s\n" % output.strip())

    # Split alignments into files
    if in_args.split_to_files:
        in_args.in_place = True
        out_dir = os.path.abspath(in_args.split_to_files[0])
        filename = in_args.split_to_files[1]
        os.makedirs(out_dir, exist_ok=True)
        check_quiet = in_args.quiet  # 'quiet' must be toggled to 'on' _print_recs() here.
        in_args.quiet = True
        for indx, buddy in enumerate(split_alignbuddy(alignbuddy)):
            alignbuddy.alignments = buddy.alignments
            ext = _format_to_extension(alignbuddy.out_format)
            in_args.alignment[0] = "%s/%s_%s.%s" % (out_dir, filename, '{:0>4d}'.format(indx + 1), ext)
            _stderr("New file: %s\n" % in_args.alignment[0], check_quiet)
            open(in_args.alignment[0], "w").close()
            _print_aligments(alignbuddy)


