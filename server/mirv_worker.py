#################################################################
# @Program: miRvestigator                                       #
# @Version: 2                                                   #
# @Author: Chris Plaisier                                       #
# @Author: Christopher Bare                                     #
# @Sponsored by:                                                #
# Nitin Baliga, ISB                                             #
# Institute for Systems Biology                                 #
# 1441 North 34th Street                                        #
# Seattle, Washington  98103-8904                               #
# (216) 732-2139                                                #
# @Also Sponsored by:                                           #
# Luxembourg Systems Biology Grant                              #
#                                                               #
# If this program is used in your analysis please mention who   #
# built it. Thanks. :-)                                         #
#                                                               #
# Copyright (C) 2010 by Institute for Systems Biology,          #
# Seattle, Washington, USA.  All rights reserved.               #
#                                                               #
# This source code is distributed under the GNU Lesser          #
# General Public License, the text of which is available at:    #
#   http://www.gnu.org/copyleft/lesser.html                     #
#################################################################

import sys, re, os, math, shutil
from subprocess import *
from copy import deepcopy
from random import sample, randint
import cPickle

# Custom libraries
from miRvestigator import miRvestigator
from pssm import pssm
from mirv_db import update_job_status, set_genes_annotated, store_motif, store_mirvestigator_scores, get_species_by_mirbase_id, map_genes_to_entrez_ids
import conf

# Libraries for plotting
import numpy, corebio                     # http://numpy.scipy.org and http://code.google.com/p/corebio/
from numpy import array, float64, log10   # http://numpy.scipy.org
from weblogolib import *                  # http://code.google.com/p/weblogo/

# Plot a PSSM using weblogo
def plotPssm(pssm, fileName):
    dist = numpy.array( pssm.getMatrix(), numpy.float64 ) 
    data = LogoData.from_counts(corebio.seq.unambiguous_rna_alphabet, dist*100)
    options = LogoOptions()
    options.color_scheme = colorscheme.nucleotide
    format = LogoFormat(data, options)
    fout = open(fileName, 'w')
    png_formatter(data, format, fout)
    fout.close()

# Reverse complement
def reverseMe(seq):
    seq = list(seq)
    seq.reverse()
    return ''.join(seq)

# Complement
def complement(seq):
    complement = {'A':'T', 'T':'A', 'C':'G', 'G':'C', 'N':'N', 'U':'A'}
    complseq = [complement[base] for base in seq]
    return complseq

# Reverse complement
def reverseComplement(seq):
    seq = list(seq)
    seq.reverse()
    return ''.join(complement(seq))

# ViennaRNA RNAduplex to get minimum free energy (MFE) for
# putative target sites.
def rnaDuplex(motif,matches):
    # Make a file to pipe in the motif consensus a new line then a match
    duplexMe = []
    for match in matches:
        duplexMe.append(reverseComplement(motif))
        duplexMe.append(match.strip().lstrip('[').rstrip(']'))
    
    # Run RNAduplex
    errOut = open(conf.tmp_dir + '/rnaDuplex.stderr.out','w')
    rnaDuplexProc = Popen("RNAduplex", shell=True,stdin=PIPE,stdout=PIPE,stderr=errOut)
    output = rnaDuplexProc.communicate('\n'.join(duplexMe))[0]
    # Read results and parse out MFE
    mfe = []
    for line in output.split('\n'):
        if not line.strip()=='':
            mfe.append(([i for i in (line.split(':')[1]).replace('(',' ').replace(')',' ').strip().split(' ') if i])[1])
    return mfe

# Run weeder and parse its output
# First weederTFBS -W 6 -e 1, then weederTFBS -W 8 -e 2, and finally adviser
# The weeder program can be found at:  http://159.149.109.9/modtools/
# I modified the C code and recompiled to make Weeder look for the FreqFiles
# folder in /local/FreqFiles. Then I made symbolic links in my PATH so that
# weeder could be run from the command line as weederlauncher. You will also
# have to add weederTFBS.out and adviser.out to the PATH in order to run.
def weeder(seqFile=None, percTargets=50, revComp=False, bgModel='HS'):
    if not os.path.exists(conf.tmp_dir+'/weeder'):
        os.makedirs(conf.tmp_dir+'/weeder')

    # Note that we use a slightly hacked version of weeder. Weederlauncher has
    # hard-coded paths to the other executables, and weederlauncher and 
    # weederTFBS have hard-coded paths to the FreqFiles directory. We hacked
    # those to point to our directories.

    # First run weederTFBS for 6bp motifs
    weederArgs = ' '+str(seqFile)+' '+str(bgModel)+' small T50'
    if revComp==True:
        weederArgs += ' -S'
    errOut = open(conf.tmp_dir+'/weeder/stderr.out','w')
    weederProc = Popen("weederlauncher " + weederArgs, shell=True,stdout=PIPE,stderr=errOut)
    output = weederProc.communicate()
    
    """# First run weederTFBS for 6bp motifs
    weederArgs = '-f '+str(seqFile)+' -W 6 -e 1 -O HS -R '+str(percTargets)
    if revComp==True:
        weederArgs += ' -S'
    errOut = open(conf.tmp_dir+'/weeder/stderr.out','w')
    weederProc = Popen("weeder " + weederArgs, shell=True,stdout=PIPE,stderr=errOut)
    output = weederProc.communicate()
    
    # Second run weederTFBS for 8bp motifs
    weederArgs = '-f '+str(seqFile)+' -W 8 -e 2 -O HS -R '+str(percTargets)
    if revComp==True:
        weederArgs += ' -S'
    weederProc = Popen("weeder " + weederArgs, shell=True,stdout=PIPE,stderr=errOut)
    output = weederProc.communicate()
    
    # Finally run adviser
    weederArgs = str(seqFile)
    weederProc = Popen("adviser " + weederArgs, shell=True,stdout=PIPE,stderr=errOut)
    output = weederProc.communicate()
    errOut.close()
    """

    # Now parse output from weeder
    PSSMs = []
    output = open(str(seqFile)+'.wee','r')
    outLines = [line for line in output.readlines() if line.strip()]
    hitBp = {}
    # Get top hit of 6bp look for "1)"
    while 1:
        outLine = outLines.pop(0)
        if not outLine.find('1) ') == -1:
            break
    hitBp[6] = outLine.strip().split(' ')[1:]

    # Scroll to where the 8bp reads wll be
    while 1:
        outLine = outLines.pop(0)
        if not outLine.find('Searching for motifs of length 8') == -1:
            break

    # Get top hit of 8bp look for "1)"
    while 1:
        outLine = outLines.pop(0)
        if not outLine.find('1) ') == -1:
            break
    hitBp[8] = outLine.strip().split(' ')[1:]

    # Scroll to where the 8bp reads wll be
    while 1:
        outLine = outLines.pop(0)
        if not outLine.find('Your sequences:') == -1:
            break
    
    # Get into the highest ranking motifs
    seqDict = {}
    while 1:
        outLine = outLines.pop(0)
        if not outLine.find('**** MY ADVICE ****') == -1:
            break
        splitUp = outLine.strip().split(' ')
        seqDict[splitUp[1]] = splitUp[3].lstrip('>')

    # Get into the highest ranking motifs
    while 1:
        outLine = outLines.pop(0)
        if not outLine.find('Interesting motifs (highest-ranking)') == -1:
            break
    while 1:
        name = outLines.pop(0).strip() # Get match
        if not name.find('(not highest-ranking)') == -1:
            break
        # Get redundant motifs
        outLines.pop(0)
        redMotifs = [i for i in outLines.pop(0).strip().split(' ') if not i=='-']
        outLines.pop(0)
        outLines.pop(0)
        line = outLines.pop(0)
        instances = []
        matches = []
        while line.find('Frequency Matrix') == -1:
            splitUp = [i for i in line.strip().split(' ') if i]
            instances.append({'gene':seqDict[splitUp[0]], 'strand':splitUp[1], 'site':splitUp[2], 'start':splitUp[3], 'match':splitUp[4].lstrip('(').rstrip(')'), 'mfe':rnaDuplex(name,[splitUp[2]])[0] })
            line = outLines.pop(0)
        # Read in Frequency Matrix
        outLines.pop(0)
        outLines.pop(0)
        matrix = []
        col = outLines.pop(0)
        while col.find('======') == -1:
            nums = [i for i in col.strip().split('\t')[1].split(' ') if i]
            colSum = 0
            for i in nums:
                colSum += int(i.strip())
            matrix += [[ float(nums[0])/float(colSum), float(nums[1])/float(colSum), float(nums[2])/float(colSum), float(nums[3])/float(colSum)]]
            col = outLines.pop(0)
        PSSMs += [pssm(biclusterName=name,nsites=instances,eValue=hitBp[len(matrix)][1],pssm=matrix,genes=redMotifs)]
    return PSSMs


def run(job_uuid, genes, geneId, seedModels, wobble, cut, motifSizes, jobName, mirbase_species, bgModel, topRet=10, viral=False):

    species = get_species_by_mirbase_id(mirbase_species)
    if bgModel=='3p':
        bgModel = species['weeder']
    else:
        bgModel = species['weeder'].rstrip('3P')
    sequence_file = conf.data_dir+"/p3utrSeqs_" + species['ucsc_name'] + ".csv"

    cut = float(cut)
    curRunNum = randint(0,1000000)

    # translate gene identifiers to entrez IDs
    print "translating gene identifiers from %s to entrez IDs" % (geneId)
    genes = map_genes_to_entrez_ids(job_uuid, geneId, mirbase_species)
    print "genes = " + str(genes)

    # 1. Read in sequences
    seqFile = open(sequence_file,'r')
    seqLines = seqFile.readlines()
    ids = [i.strip().split(',')[0].upper() for i in seqLines]
    sequences = [i.strip().split(',')[1] for i in seqLines]
    seqs = dict(zip(ids,sequences))
    seqFile.close()

    #update_job_status(job, "finished reading sequence file")

    # 2. Get sequences for each target
    miRSeqs = {}
    for gene in genes:
        if gene in seqs:
            miRSeqs[gene] = seqs[gene]

    # if there are no matching sequences, bail out w/ a reasonable error message.
    if (len(miRSeqs)==0):
        print("no matching sequences found for genes in job " + str(job_uuid))
        update_job_status(job_uuid, "error", "No sequences found for the genes entered.")
        return False

    # record whether a sequence was found for each gene
    # previously stored when job was created (create_job_in_db)
    set_genes_annotated(job_uuid, miRSeqs)

    # 3. Make a FASTA file
    if not os.path.exists(conf.tmp_dir+'/fasta'):
        os.makedirs(conf.tmp_dir+'/fasta')
    fastaFile = open(conf.tmp_dir+'/fasta/tmp'+str(curRunNum)+'.fasta','w')
    for seq in miRSeqs:
        fastaFile.write('>'+str(seq)+'\n'+str(miRSeqs[seq])+'\n')
    fastaFile.close()

    # 4. Run weeder
    print 'Running weeder!'
    update_job_status(job_uuid, "running weeder")
    weederPSSMs1 = weeder(seqFile=conf.tmp_dir+'/fasta/tmp'+str(curRunNum)+'.fasta', percTargets=50, revComp=False, bgModel=bgModel)

    # 4a. Take only selected size motifs
    weederPSSMsTmp = []
    for pssm1 in weederPSSMs1:
        if 6 in motifSizes and len(pssm1.getName())==6:
            weederPSSMsTmp.append(deepcopy(pssm1))
            plotPssm(pssm1,conf.pssm_images_dir+'/'+str(job_uuid)+'_'+pssm1.getName()+'.png')
        if 8 in motifSizes and len(pssm1.getName())==8:
            weederPSSMsTmp.append(deepcopy(pssm1))
            plotPssm(pssm1,conf.pssm_images_dir+'/'+str(job_uuid)+'_'+pssm1.getName()+'.png')
        print("pssm name = " + pssm1.getName())
    weederPSSMs1 = deepcopy(weederPSSMsTmp)
    del weederPSSMsTmp

    # 5. Run miRvestigator HMM
    update_job_status(job_uuid, "computing miRvestigator HMM")
    mV = miRvestigator(weederPSSMs1, seqs.values(),
                       seedModel=seedModels,
                       minor=True,
                       p5=True, p3=True,
                       wobble=wobble, wobbleCut=cut,
                       textOut=False,
                       species=mirbase_species,
                       viral = viral)

    # 6. Read in miRNAs to get mature miRNA ids
    # import gzip
    # miRNAFile = gzip.open('mature.fa.gz','r')
    # miRNADict = {}
    # while 1:
    #     miRNALine = miRNAFile.readline()
    #     seqLine = miRNAFile.readline()
    #     if not miRNALine:
    #         break
    #     # Get the miRNA name
    #     miRNAData = miRNALine.lstrip('>').split(' ')
    #     curMiRNA = miRNAData[0]
    #     if (curMiRNA.split('-'))[0]=='hsa':
    #         miRNADict[curMiRNA] = miRNAData[1]
    # miRNAFile.close()

    # 6. Clean-up after yerself
    os.remove(conf.tmp_dir+'/fasta/tmp'+str(curRunNum)+'.fasta')
    os.remove(conf.tmp_dir+'/fasta/tmp'+str(curRunNum)+'.fasta.wee')
    os.remove(conf.tmp_dir+'/fasta/tmp'+str(curRunNum)+'.fasta.mix')
    os.remove(conf.tmp_dir+'/fasta/tmp'+str(curRunNum)+'.fasta.html')

    # 7. write output to database
    update_job_status(job_uuid, "compiling results")

    for pssm in weederPSSMs1:
        motif_id = store_motif(job_uuid, pssm)
        scores = mV.getScoreList(pssm.getName())
        store_mirvestigator_scores(motif_id, scores)


    update_job_status(job_uuid, "done")
    return True




