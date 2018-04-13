# -*- coding: utf-8 -*-
print "Loading HaasoscopeLib.py"

# You might adjust these, just override them before calling construct()
num_board = 1 # Number of Haasoscope boards to read out
ram_width = 9 # width in bits of sample ram to use (e.g. 9==512 samples, 12(max)==4096 samples)
max10adcchans = []#[(0,110),(0,118),(1,110),(1,118)] #max10adc channels to draw (board, channel on board), channels: 110=ain1, 111=pin6, ..., 118=pin14, 119=temp
sendincrement=0 # 0 would skip 2**0=1 byte each time, i.e. send all bytes, 10 is good for lockin mode (sends just 4 samples)
num_chan_per_board = 4 # number of high-speed ADC channels on a Haasoscope board

from serial import Serial, SerialException
from struct import unpack
import numpy as np
import time, sys
import matplotlib
dofast=True #do the fast way of redrawing, just the specific things that could have likely changed
if dofast: matplotlib.use('Qt4Agg')
import matplotlib.pyplot as plt
from scipy.signal import resample
import serial.tools.list_ports
import json, os
import scipy.optimize

class Haasoscope():
    
    def construct(self):
        self.num_samples = pow(2,ram_width)/pow(2,sendincrement) # num samples per channel, max is pow(2,ram_width)/pow(2,0)=4096
        self.num_bytes = self.num_samples*num_chan_per_board #num bytes per board
        self.nsamp=pow(2,ram_width)-1 #samples for each max10 adc channel (4095 max (not sure why it's 1 less...))
        print "num main ADC and max10adc bytes for all boards = ",self.num_bytes*num_board,"and",len(max10adcchans)*self.nsamp
        self.serialdelaytimerwait=0 #150 # 600 # delay (in 2 us steps) between each 32 bytes of serial output (set to 600 for some slow USB serial setups, but 0 normally)
        self.brate = 1500000 #serial baud rate #1500000 #115200
        self.sertimeout = 3.0 #time to wait for serial response #3.0, num_bytes*8*10.0/brate, or None
        self.clkrate=125.0 # ADC sample rate in MHz
        self.serport="" # the name of the serial port on your computer, connected to Haasoscope, like /dev/ttyUSB0 or COM8, leave blank to detect automatically!
        self.usbport=[] # the names of the USB2 ports on your computer, connected to Haasoscope, leave blank to detect automatically!
        self.usbser=[]
        self.lines = []
        self.otherlines = []
        self.texts = []
        self.xdata=np.arange(self.num_samples)
        self.ydata = []
        ysampdatat=np.zeros(self.nsamp*len(max10adcchans)); self.ysampdata=np.reshape(ysampdatat,(len(max10adcchans),self.nsamp))
        self.xsampdata=np.arange(self.nsamp)
        self.paused=False
        self.getone=False
        self.rolltrigger=True #roll the trigger
        self.average=False #will average every 2 samples
        self.rising=True #trigger on rising edge (or else falling edge)
        self.dogrid=True #redraw the grid
        self.chanforscreen=0 #channel to draw on the mini-display
        self.triggertimethresh=5 #samples for which the trigger must be over/under threshold
        self.downsample=2 #adc speed reduction, log 2... so 0 (none), 1(factor 2), 2(factor 4), etc.
        self.dofft=False #drawing the FFT plot
        self.dousb=False #whether to use USB2 output
        self.sincresample=0 # amount of resampling to do (sinx/x)
        self.dogetotherdata=False # whether to read other calculated data like TDC
        self.domaindrawing=True # whether to update the main window data and redraw it
        self.selectedchannel=0 #what channel some actions apply to
        self.selectedmax10channel=0 #what max10 channel is selected
        self.autorearm=False #whether to automatically rearm the trigger after each event, or wait for a signal from software
        self.dohighres=False #whether to do averaging during downsampling or not (turned on by default during startup, and off again during shutdown)
        self.useexttrig=False #whether to use the external trigger input
        self.autocalibchannel=-1 #which channel we are auto-calibrating
        self.autocalibgainac=0 #which stage of gain and acdc we are auto-calibrating
        self.db = False #debugging #True #False
    
        self.dolockin=False # read lockin info
        self.dolockinplot=True # plot the lockin info
        self.lockinanalyzedataboard=0 # the board to analyze lockin info from
        self.debuglockin=False #debugging of lockin calculations #True #False
        self.reffreq = 0.008 #MHz of reference signal on chan 3 for lockin calculations
        self.refsinchan = 3 #the channel number of the ref input signal (for auto reffreq calculation via sin fit)
        
        self.yscale = 7.5 # Vpp for full scale
        self.min_y = -self.yscale/2. #-4.0 #0 ADC
        self.max_y = self.yscale/2. #4.0 #256 ADC
        self.xscaling=1.e0 # for the x-axis scale
        self.lowdaclevel=np.ones(num_board*num_chan_per_board)*2050 # these hold the user set levels for each gain combination
        self.highdaclevel=np.ones(num_board*num_chan_per_board)*2800
        self.lowdaclevelsuper=np.ones(num_board*num_chan_per_board)*120
        self.highdaclevelsuper=np.ones(num_board*num_chan_per_board)*50
        self.lowdaclevelac=np.ones(num_board*num_chan_per_board)*2250 # these hold the user set levels for each gain combination in ac coupling mode
        self.highdaclevelac=np.ones(num_board*num_chan_per_board)*4100
        self.lowdaclevelsuperac=np.ones(num_board*num_chan_per_board)*2100
        self.highdaclevelsuperac=np.ones(num_board*num_chan_per_board)*2800
        self.chanlevel=np.ones(num_board*num_chan_per_board)*self.lowdaclevel # the current level for each channel, initially set to lowdaclevel (x1)
        self.gain=np.ones(num_board*num_chan_per_board, dtype=int) # 1 is low gain, 0 is high gain (x10)
        self.supergain=np.ones(num_board*num_chan_per_board, dtype=int) # 1 is normal gain, 0 is super gain (x100)
        self.acdc=np.ones(num_board*num_chan_per_board, dtype=int) # 1 is dc, 0 is ac
        self.trigsactive=np.ones(num_board*num_chan_per_board, dtype=int) # 1 is triggering on that channel, 0 is not triggering on it
        self.dooversample=np.zeros(num_board*num_chan_per_board, dtype=int) # 1 is oversampling, 0 is no oversampling
        self.maxdownsample=10 # slowest I can run
        
        #These hold the state of the IO expanders
        self.a20= int('f0',16) # oversamp (set bits 0,1 to 0 to send 0->2 and 1->3) / gain (set second char to 0 for low gain)
        self.b20= int('0f',16)  # shdn (set first char to 0 to turn on) / ac coupling (set second char to f for DC, 0 for AC)
        self.a21= int('00',16) # leds (on is 1)
        self.b21= int('00',16)# free pins
    
    def tellrolltrig(self,rt):
        #tell them to roll the trigger (a self-trigger each ~second), or not
        if rt: self.ser.write(chr(101)); print "rolling trigger"
        else:  self.ser.write(chr(102)); print "not rolling trigger"

    def tellsamplesmax10adc(self):
        #tell it the number of samples to use for the 1MHz internal Max10 ADC
        self.ser.write(chr(120))
        myb=bytearray.fromhex('{:04x}'.format(self.nsamp))
        self.ser.write(chr(myb[0]))
        self.ser.write(chr(myb[1]))
        if self.db: print "Nsamp for max10 ADC is",256*myb[0]+1*myb[1]
    
    def settriggerpoint(self,tp):
        #tell it the trigger point
        self.ser.write(chr(121))
        offset=5 #small offset due to drawing and delay
        myb=bytearray.fromhex('{:04x}'.format(tp+offset))
        self.ser.write(chr(myb[0]))
        self.ser.write(chr(myb[1]))
        print "Trigger point is",256*myb[0]+1*myb[1]-offset

    def tellsamplessend(self):
        #tell it the number of samples to send
        self.ser.write(chr(122))
        myb=bytearray.fromhex('{:04x}'.format(self.num_samples*pow(2,sendincrement))) # or 0 for all, or num_samples*pow(2,sendincrement)
        self.ser.write(chr(myb[0]))
        self.ser.write(chr(myb[1]))
        print "num samples is",256*myb[0]+1*myb[1]
    
    def telllockinnumtoshift(self,numtoshift):
        #tell it the number of samples to shift when calculating 90deg outofphase sum for lockin
        self.ser.write(chr(138))
        myb=bytearray.fromhex('{:04x}'.format(numtoshift))
        self.ser.write(chr(myb[0]))
        self.ser.write(chr(myb[1]))
        if self.db: print "lockinnumtoshift is",256*myb[0]+1*myb[1]
        
    def tellserialdelaytimerwait(self):
        #tell it the number of microseconds to wait between every 32 (64?) bytes of serial output (for some slow USB serial setups)
        self.ser.write(chr(135))
        myb=bytearray.fromhex('{:04x}'.format(self.serialdelaytimerwait))
        self.ser.write(chr(myb[0]))
        self.ser.write(chr(myb[1]))
        print "serialdelaytimerwait is",256*myb[0]+1*myb[1]
    
    def tellbytesskip(self):
        #tell it the number of bytes to skip after each send, log2
        self.ser.write(chr(123))
        self.ser.write(chr(sendincrement))
        print "send increment is",sendincrement
    
    def telltickstowait(self): #usually downsample+4
        #tell it the number of clock ticks to wait, log2, between sending bytes
        if self.dousb: ds=self.downsample-2
        else: ds=self.downsample-3
        if ds<1: ds=1
        self.ser.write(chr(125))
        self.ser.write(chr(ds))
        if self.db: print "clockbitstowait is",ds
    
    def tellminidisplaychan(self,ch):
        #tell it the channel to show on the mini-display
        self.ser.write(chr(126))
        self.ser.write(chr(ch))
        print "chanforscreen is",ch
    
    def settriggerthresh(self,tp):
        #tell it the trigger threshold
        self.ser.write(chr(127))
        tp=255-tp # need to flip it due to op amp
        self.ser.write(chr(tp))
        print "Trigger threshold is",tp
        
    def settriggerthresh2(self,tp):
        #tell it the high trigger threshold (must be below this to trigger)
        self.ser.write(chr(140))
        tp=255-tp # need to flip it due to op amp
        self.ser.write(chr(tp))
        print "Trigger high threshold is",tp
    
    def settriggertype(self,tp):
        #tell it the trigger type: rising, falling, either, ...
        self.ser.write(chr(128))
        self.ser.write(chr(tp))
        print "Trigger type is",tp
        
    def settriggertime(self,ttt):
        #tell it the trigger time over/under threshold required
        if ttt>self.num_samples and ttt>10:
            print "trigger time over/under thresh can't be bigger than num samples",self.num_samples; return
        usedownsamplefortriggertot=True
        if usedownsamplefortriggertot: ttt+=pow(2,12) #set bit [ram_width] (max) = 1
        self.ser.write(chr(129))
        myb=bytearray.fromhex('{:04x}'.format(ttt))
        self.ser.write(chr(myb[0]))
        self.ser.write(chr(myb[1]))
        print "trigger time over/under thresh now",256*myb[0]+1*myb[1]-pow(2,12),"and usedownsamplefortriggertot is",usedownsamplefortriggertot
    
    def writefirmchan(self,chan):
        theboard = num_board-1-chan/num_chan_per_board
        chanonboard = chan%num_chan_per_board
        self.ser.write(chr(theboard*num_chan_per_board+chanonboard)) # the channels are numbered differently in the firmware
    
    def setdaclevelforchan(self,chan,level):
        if level>4096*2-1: 
            print "level can't be bigger than 2**13-1=4096*2-1"
            level=4096*2-1
        if level<0: 
            print "level can't be less than 0"
            level=0
        theboard = num_board-1-chan/num_chan_per_board
        chanonboard = chan%num_chan_per_board
        self.setdac(chanonboard,level,theboard)
        self.chanlevel[chan]=level
        if not self.firstdrawtext: self.drawtext()
        if self.db: print "DAC level set for channel",chan,"to",level,"which is chan",chanonboard,"on board",theboard
    
    def tellSPIsetup(self,what):
        time.sleep(.01) #pause to make sure other SPI writng is done
        self.ser.write(chr(131))
        myb=bytearray.fromhex('06 10') #default    
        #SPIsenddata[14:8]=7'h08;//Common mode bias voltages
        #SPIsenddata[7:0]=8'b00000000;//off //0x00
        #SPIsenddata[7:0]=8'b11111111;//on 0.45V //0xff
        #SPIsenddata[7:0]=8'b11001100;//on 0.9V //0xcc
        #SPIsenddata[7:0]=8'b10111011;//on 1.35V //0xbb
        if what==0: myb=bytearray.fromhex('08 00') #not connected, 0.9V
        if what==1: myb=bytearray.fromhex('08 ff') #0.45V
        if what==2: myb=bytearray.fromhex('08 dd') #0.75V
        if what==3: myb=bytearray.fromhex('08 cc') #0.9V
        if what==4: myb=bytearray.fromhex('08 99') #1.05V
        if what==5: myb=bytearray.fromhex('08 aa') #1.2V
        if what==6: myb=bytearray.fromhex('08 bb') #1.35V    
        #SPIsenddata[14:8]=7'h06; //Clock Divide/Data Format/Test Pattern
        #SPIsenddata[7:0]=8'b01010000;//do test pattern in offset binary // 0x50
        #SPIsenddata[7:0]=8'b00010000;//do offset binary //0x10
        if what==10: myb=bytearray.fromhex('06 50') #test pattern output
        if what==11: myb=bytearray.fromhex('06 10') #offset binary output + no clock divide
        if what==12: myb=bytearray.fromhex('06 11') #offset binary output + divide clock by 2
        if what==13: myb=bytearray.fromhex('06 12') #offset binary output + divide clock by 4            
        if what==20: myb=bytearray.fromhex('04 1b') #150 Ohm termination chA
        if what==21: myb=bytearray.fromhex('04 00') #50 Ohm termination chA (default)
        if what==22: myb=bytearray.fromhex('05 1b') #150 Ohm termination chB
        if what==23: myb=bytearray.fromhex('05 00') #50 Ohm termination chB (default)        
        if what==30: myb=bytearray.fromhex('01 02') #multiplexed, with chA first
        if what==31: myb=bytearray.fromhex('01 06') #multiplexed, with chB first
        if what==32: myb=bytearray.fromhex('01 00') # not multiplexed output        
        self.ser.write(chr(myb[0]));	self.ser.write(chr(myb[1])); #write it!
        print "tell SPI setup:",format(myb[0],'02x'),format(myb[1],'02x')
        time.sleep(.01) #pause to make sure other SPI writng is done
    
    # testBit() returns a nonzero result, 2**offset, if the bit at 'offset' is one.
    def testBit(self,int_type, offset):
        mask = 1 << offset
        return(int_type & mask)
    # setBit() returns an integer with the bit at 'offset' set to 1.
    def setBit(self,int_type, offset):
        mask = 1 << offset
        return(int_type | mask)
    # clearBit() returns an integer with the bit at 'offset' cleared.
    def clearBit(self,int_type, offset):
        mask = ~(1 << offset)
        return(int_type & mask)
    # toggleBit() returns an integer with the bit at 'offset' inverted, 0 -> 1 and 1 -> 0.
    def toggleBit(self,int_type, offset):
        mask = 1 << offset
        return(int_type ^ mask)
  
    def sendi2c(self,whattosend,board=200):
	time.sleep(.02)
        myb=bytearray.fromhex(whattosend)
        self.ser.write(chr(136))
        datacounttosend=len(myb)-1 #number of bytes of info to send, not counting the address
        self.ser.write(chr(datacounttosend))
        for b in np.arange(len(myb)): self.ser.write(chr(myb[b]))
        for b in np.arange(4-len(myb)): 
            self.ser.write(chr(255)) # pad with extra bytes since the command expects a total of 5 bytes (numtosend, addr, and 3 more bytes)
        self.ser.write(chr(board)) #200 (default) will address message to all boards, otherwise only the given board ID will listen
        if self.db: print "Tell i2c:","bytestosend:",datacounttosend," and address/data:",whattosend,"for board",board
        time.sleep(.02)
    
    def setupi2c(self):
        self.sendi2c("20 00 00") #port A on IOexp 1 are outputs
        self.sendi2c("20 01 00") #port B on IOexp 1 are outputs
        self.sendi2c("21 00 00") #port A on IOexp 2 are outputs
        self.sendi2c("21 01 00") #port B on IOexp 2 are outputs
        self.sendi2c("20 12 "+ ('%0*x' % (2,self.a20)) ) #port A of IOexp 1
        self.sendi2c("20 13 "+ ('%0*x' % (2,self.b20)) ) #port B of IOexp 1
        self.sendi2c("21 12 "+ ('%0*x' % (2,self.a21)) ) #port A of IOexp 2
        self.sendi2c("21 13 "+ ('%0*x' % (2,self.b21)) ) #port B of IOexp 2
        print "initialized all i2c ports and set to starting values"
            
    def setdac(self,chan,val,board):        
        if chan==0: c="50"
        elif chan==1: c="52"
        elif chan==2: c="54"
        elif chan==3: c="56"
        else:
            print "channel",chan,"out of range 0-3"
            return        
        if val>4096*2-1 or val<0:
            print "value",val,"out of range 0-(4096*2-1)"
            return
        #d="0" # Vdd ref (0-3.3V, but noisy?)
        d="8" #internal ref, gain=1 (0-2V)
        if val>4095:
            d="9" #internal ref, gain=2 (0-4V)
            val/=2
        self.sendi2c("60 "+c+d+('%0*x' % (3,val)),  board) #DAC, can go from 000 to 0fff in last 12 bits, and only send to the selected board
    
    def shutdownadcs(self):
        self.b20= int('ff',16)  # shdn (set first char to f to turn off) / ac coupling (?)
        self.sendi2c("20 13 "+ ('%0*x' % (2,self.b20)) ) #port B of IOexp 1
        print "shut down adcs"
        
    def testi2c(self):
        print "test i2c"
        dotest=1 # what to test
        if dotest==0:
            # IO expander 1            
            self.sendi2c("20 12 ff") #turn on all port A of IOexp 1 (12 means A, ff is which of the 8 bits to turn on)
            self.sendi2c("20 13 ff") #turn on all port B of IOexp 1 (13 means B, ff is which of the 8 bits to turn on)
            time.sleep(3)
            self.sendi2c("20 12 00") #turn off all port A of IOexp 1
            self.sendi2c("20 13 00") #turn off all port B of IOexp 1
        elif dotest==1:
            #Test the DAC
            self.setdac(0,0)
            time.sleep(3)
            self.setdac(0,1200)
        elif dotest==2:
            #toggle led 1, at 0x21 a0
            self.a21=self.setBit(self.a21,0); self.sendi2c("21 12 "+ ('%0*x' % (2,self.a21)) )
            time.sleep(3)
            self.a21=self.clearBit(self.a21,0); self.sendi2c("21 12 "+ ('%0*x' % (2,self.a21)) )

    def toggledousb(self):#toggle whether to read over FT232H USB or not
        if len(self.usbser)==0:
            self.dousb=False
            print "usb2 connection not available"
        else:
            self.dousb = not self.dousb
            self.ser.write(chr(137))
            print "dousb toggled to",self.dousb
            if self.dousb: print "rate theoretically",round(4000000./(self.num_bytes*num_board+len(max10adcchans)*self.nsamp),2),"Hz over USB2"
            self.telltickstowait()
    
    def togglehighres(self):#toggle whether to do highres averaging during downsampling or not
            self.ser.write(chr(143))
            self.dohighres = not self.dohighres
            print "do highres is",self.dohighres
    
    def toggleuseexttrig(self):#toggle whether to use the external trigger input or not
            self.ser.write(chr(144))
            self.useexttrig = not self.useexttrig
            print "useexttrig is",self.useexttrig
    
    def toggletriggerchan(self,tp):
        #tell it to trigger or not trigger on a given channel
        self.ser.write(chr(130))
        self.writefirmchan(tp)
        self.trigsactive[tp] = not self.trigsactive[tp]
        if len(plt.get_fignums())>0:
            origline,legline,channum = self.lined[tp]
            if self.trigsactive[tp]: self.leg.get_texts()[tp].set_color('#000000')
            else: self.leg.get_texts()[tp].set_color('#aFaFaF')
            self.figure.canvas.draw()
        print "Trigger toggled for channel",tp

    def toggleautorearm(self):
        #tell it to toggle the auto rearm of the tirgger after readout
        self.ser.write(chr(139))
        self.autorearm = not self.autorearm
        print "Trigger auto rearm now",self.autorearm
        if self.db: print "priming trigger",time.clock()
        if self.db: time.sleep(.1)
        self.ser.write(chr(100)) # prime the trigger one last time
    
    def getIDs(self):
        debug3=True
        self.uniqueID=[]
        for n in range(num_board):
            self.ser.write(chr(30+n)) #make the next board active (serial_passthrough 0) 
            self.ser.write(chr(142)) #request the unique ID
            num_other_bytes = 8
            rslt = self.ser.read(num_other_bytes)
            if len(rslt)==num_other_bytes:
                byte_array = unpack('%dB'%len(rslt),rslt) #Convert serial data to array of numbers
                self.uniqueID.append( ''.join(format(x, '02x') for x in byte_array) )
                if debug3: print "got uniqueID",self.uniqueID[n],"for board",n,", len is now",len(self.uniqueID)
            else: print "getID asked for",num_other_bytes,"bytes and got",len(rslt),"from board",n
    
    def togglesupergainchan(self,chan):
        if len(plt.get_fignums())>0: origline,legline,channum = self.lined[chan]
        if self.supergain[chan]==1:
            self.supergain[chan]=0 #x100 super gain on!
            if len(plt.get_fignums())>0:
                if self.gain[chan]==1:
                    origline.set_label("chan "+str(chan)+" x100")
                    self.leg.get_texts()[chan].set_text("chan "+str(chan)+" x100")
                else:
                    origline.set_label("chan "+str(chan)+" x1000")
                    self.leg.get_texts()[chan].set_text("chan "+str(chan)+" x1000")
        else:
            self.supergain[chan]=1 #normal gain
            if len(plt.get_fignums())>0:
                if self.gain[chan]==1:
                    origline.set_label("chan "+str(chan))
                    self.leg.get_texts()[chan].set_text("chan "+str(chan))
                else:
                    origline.set_label("chan "+str(chan)+" x10")
                    self.leg.get_texts()[chan].set_text("chan "+str(chan)+" x10")
        self.setdacvalue()
        if len(plt.get_fignums())>0: self.figure.canvas.draw()
        print "Supergain switched for channel",chan,"to",self.gain[chan]
    
    def tellswitchgain(self,chan):
        #tell it to switch the gain of a channel
        self.ser.write(chr(134))
        self.writefirmchan(chan)
        if len(plt.get_fignums())>0: origline,legline,channum = self.lined[chan]
        if self.gain[chan]==1:
            self.gain[chan]=0 # x10 gain on!
            if len(plt.get_fignums())>0:
                if self.supergain[chan]==1:
                    origline.set_label("chan "+str(chan)+" x10")
                    self.leg.get_texts()[chan].set_text("chan "+str(chan)+" x10")
                else:
                    origline.set_label("chan "+str(chan)+" x1000")
                    self.leg.get_texts()[chan].set_text("chan "+str(chan)+" x1000")
        else:
            self.gain[chan]=1 #low gain
            if len(plt.get_fignums())>0:
                if self.supergain[chan]==1:
                    origline.set_label("chan "+str(chan))
                    self.leg.get_texts()[chan].set_text("chan "+str(chan))
                else:
                    origline.set_label("chan "+str(chan)+" x100")
                    self.leg.get_texts()[chan].set_text("chan "+str(chan)+" x100")
        self.selectedchannel=chan # needed for setdacvalue
        self.setdacvalue()
        if len(plt.get_fignums())>0: self.figure.canvas.draw()
        print "Gain switched for channel",chan,"to",self.gain[chan]

    def oversamp(self,chan):
        #tell it to toggle oversampling for this channel
        chanonboard = chan%num_chan_per_board
        if chanonboard>1: return
        self.telldownsample(0) # must be in max sampling mode for oversampling to make sense
        self.dooversample[self.selectedchannel] = not self.dooversample[self.selectedchannel];
        print "oversample is now",self.dooversample[self.selectedchannel],"for channel",chan
        self.ser.write(chr(141))
        self.writefirmchan(chan)
        self.drawtext()
        self.figure.canvas.draw()

    def resetchans(self):
        for chan in np.arange(num_board*num_chan_per_board):
            if self.gain[chan]==0:
                self.tellswitchgain(chan) # set all gains back to low gain
            if  self.trigsactive[chan]==0:
                self.toggletriggerchan(chan) # set all trigger channels back to active
            if self.dooversample[chan]: 
                self.oversamp(chan) # set all channels back to no oversampling
    
    def setbacktoserialreadout(self):
        if self.dousb:    
            self.ser.write(chr(137))
            self.dousb=False
            print "dousb set back to",self.dousb
    
    def telldownsample(self,ds):
        #tell it the amount to downsample, log2... so 0 (none), 1(factor 2), 2(factor 4), etc.
        if max(self.dooversample)>0: print "can't change sampling rate while oversampling - must be fastest!"; return False
        if ds>self.maxdownsample: print "downsample >",self.maxdownsample,"doesn't work well...and I get bored running that slow!"; return False
        if ds<0: print "downsample can't be <0 !"; return False
        if self.dolockin and ds<2: print "downsample can't be <2 in lockin mode !"; return False
        self.ser.write(chr(124))
        self.ser.write(chr(ds))
        self.downsample=ds
        if self.db: print "downsample is",self.downsample        
        if self.dolockin:
            twoforoversampling=1
            uspersample=(1.0/self.clkrate)*pow(2,self.downsample)/twoforoversampling # us per sample = 10 ns * 2^downsample
            numtoshiftf= 1.0/self.reffreq/4.0 / uspersample
            print "would like to shift by",round(numtoshiftf,4),"samples, and uspersample is",uspersample
            self.numtoshift = int(round(numtoshiftf,0))+0 # shift by 90 deg
            self.telllockinnumtoshift(self.numtoshift)
        else:
            self.telllockinnumtoshift(0) # tells the FPGA to not send lockin info    
        self.telltickstowait()
        self.setxaxis()
        return True # successful (parameter within OK range)

    def setxaxis(self):
        if not hasattr(self,'ax'): return
        xscale =  self.num_samples/2.0*(1000.0*pow(2,self.downsample)/self.clkrate)
        if xscale<1e3: 
            self.ax.set_xlabel("Time (ns)")
            self.min_x = -xscale
            self.max_x = xscale
            self.xscaling=1.e0
        elif xscale<1e6: 
            self.ax.set_xlabel("Time (us)")
            self.min_x = -xscale/1e3
            self.max_x = xscale/1e3
            self.xscaling=1.e3
        else:
            self.ax.set_xlabel("Time (ms)")
            self.min_x = -xscale/1e6
            self.max_x = xscale/1e6
            self.xscaling=1.e6
        self.ax.set_xlim(self.min_x, self.max_x)
        self.ax.xaxis.set_major_locator(plt.MultipleLocator( (self.max_x*1000/1024-self.min_x*1000/1024)/8 ))
        self.figure.canvas.draw()
    
    def setyaxis(self):
        self.ax.set_ylim(self.min_y, self.max_y)
        self.ax.set_ylabel("Volts") #("ADC value")
        self.ax.yaxis.set_major_locator(plt.MultipleLocator(1.0))
        self.ax.yaxis.set_minor_locator(plt.MultipleLocator(0.5))
        #self.ax.set_autoscaley_on(True)
        self.figure.canvas.draw()    
        
    def chantext(self):
        text = "Selected:"
        text +="\nChannel: "+str(self.selectedchannel)
        text +="\nLevel="+str(self.chanlevel[self.selectedchannel])
        text +="\nDC coupled="+str(self.acdc[self.selectedchannel])
        text +="\nTriggering="+str(self.trigsactive[self.selectedchannel])
        chanonboard = self.selectedchannel%num_chan_per_board
        if chanonboard<2:
            if self.dooversample[self.selectedchannel]: text+= "\nOversampled x2"
        else:
            if self.dooversample[self.selectedchannel-2]: text+= "\nDisabled (oversampling)"
        #text+="\n"
        #text+="\nmax10chan: "+str(self.selectedmax10channel)
        return text
    
    firstdrawtext=True
    needtoredrawtext=False
    def drawtext(self):
        height = 0.2 # height up from bottom to start drawing text
        if self.firstdrawtext:
            self.texts.append(self.ax.text(1.01, height, self.chantext(),horizontalalignment='left', verticalalignment='top',transform=self.ax.transAxes))
            self.firstdrawtext=False
        else:
            self.texts[0].remove()
            self.texts[0]=(self.ax.text(1.01, height, self.chantext(),horizontalalignment='left', verticalalignment='top',transform=self.ax.transAxes))
            #for txt in self.ax.texts: print txt # debugging
        self.needtoredrawtext=True
        plt.draw()
    
    def togglechannel(self,theline):
        # on the pick event, find the orig line corresponding to the
        # legend proxy line, and toggle the visibility
        origline,legline,channum = self.lined[theline]
        print "toggle",theline,"for channum",channum                
        vis = not origline.get_visible()
        origline.set_visible(vis)
        if channum < num_board*num_chan_per_board: # it's an ADC channel (not a max10adc channel or other thing)
            # If the channel was not actively triggering, and we now turned it on, or vice versa, toggle the trigger activity for this channel
            if self.trigsactive[channum] != vis: self.toggletriggerchan(channum)
        # Change the alpha on the line in the legend so we can see what lines have been toggled
        if vis: legline.set_alpha(1.0); legline.set_linewidth(2.0)
        else: legline.set_alpha(0.2); legline.set_linewidth(1.0)
    
    def pickline(self,theline):
        # on the pick event, find the orig line corresponding to the
        # legend proxy line, and toggle the visibility
        origline,legline,channum = self.lined[theline]
        if self.db: print "picked",theline,"for channum",channum
        if hasattr(self,'selectedlegline'): 
            if self.selectedorigline.get_visible(): self.selectedlegline.set_linewidth(2.0)
            else: self.selectedlegline.set_linewidth(1.0)
        legline.set_linewidth(4.0)
        self.selectedlegline=legline; self.selectedorigline=origline # remember them so we can set it back to normal later when we pick something else
        if channum < num_board*num_chan_per_board: # it's an ADC channel (not a max10adc channel or other thing)
            if self.db: print "picked a real ADC channel"
            self.selectedchannel=channum
            if self.keyShift: self.toggletriggerchan(channum)
        else:
            if self.db: print "picked a max10 ADC channel"
            self.selectedmax10channel=channum - num_board*num_chan_per_board
        self.drawtext()

    def onpick(self,event):
        if event.mouseevent.button==1: #left click
            if self.keyControl: self.togglechannel(event.artist)
            else:self.pickline(event.artist)
            plt.draw()
    
    def onclick(self,event):
        try:
            if event.button==1: #left click                
                pass
            if event.button==2: #middle click                
                self.settriggerthresh2(int(  event.ydata/(self.yscale/256.) + 128  ))                
                self.hline2 = event.ydata
                self.otherlines[2].set_data( [self.min_x, self.max_x], [self.hline2, self.hline2] )
            if event.button==3: #right click
                self.settriggerpoint(int(  (event.xdata / (1000.0*pow(2,self.downsample)/self.clkrate/self.xscaling)) +self.num_samples/2  ))
                self.settriggerthresh(int(  event.ydata/(self.yscale/256.) + 128  ))
                self.vline = event.xdata
                self.otherlines[0].set_data( [self.vline, self.vline], [self.min_y, self.max_y] ) # vertical line showing trigger time
                self.hline = event.ydata
                self.otherlines[1].set_data( [self.min_x, self.max_x], [self.hline, self.hline] ) # horizontal line showing trigger threshold
            print('%s click: button=%d, x=%d, y=%d, xdata=%f, ydata=%f' % ('double' if event.dblclick else 'single', event.button, event.x, event.y, event.xdata, event.ydata))
            return
        except TypeError: pass
    
    def adjustvertical(self,up,amount=10):
        if self.keyShift: amount*=5
        if self.keyControl: amount/=10
        #print "amount is",amount
        if self.gain[self.selectedchannel]: amount*=10 #low gain
        if self.supergain[self.selectedchannel]==0 and self.acdc[self.selectedchannel]: amount=max(1,amount/10) #super gain
        #print "now amount is",amount
        if up:
             self.chanlevel[self.selectedchannel] = self.chanlevel[self.selectedchannel] - amount
        else:
             self.chanlevel[self.selectedchannel] = self.chanlevel[self.selectedchannel] + amount
        self.rememberdacvalue()
        self.setdacvalue()
        
    def rememberdacvalue(self):
        #remember current dac level for the future to the right daclevel, depending on other settings
        if self.gain[self.selectedchannel]: # low gain
            if self.supergain[self.selectedchannel]: 
                if self.acdc[self.selectedchannel]: self.lowdaclevel[self.selectedchannel]=self.chanlevel[self.selectedchannel]
                else: self.lowdaclevelac[self.selectedchannel]=self.chanlevel[self.selectedchannel]
            else: #supergain
                if self.acdc[self.selectedchannel]: self.lowdaclevelsuper[self.selectedchannel]=self.chanlevel[self.selectedchannel] #dc super gain
                else: self.lowdaclevelsuperac[self.selectedchannel]=self.chanlevel[self.selectedchannel]
        else: # high gain
            if self.supergain[self.selectedchannel]: 
                if self.acdc[self.selectedchannel]: self.highdaclevel[self.selectedchannel]=self.chanlevel[self.selectedchannel]
                else: self.highdaclevelac[self.selectedchannel]=self.chanlevel[self.selectedchannel]
            else: #supergain
                if self.acdc[self.selectedchannel]: self.highdaclevelsuper[self.selectedchannel]=self.chanlevel[self.selectedchannel] #dc super gain
                else: self.highdaclevelsuperac[self.selectedchannel]=self.chanlevel[self.selectedchannel]
                
    def setdacvalue(self):
        #set current dac level to the remembered value, depending on other settings
        if self.gain[self.selectedchannel]: # low gain
            if self.supergain[self.selectedchannel]: 
                if self.acdc[self.selectedchannel]: self.setdaclevelforchan(self.selectedchannel,self.lowdaclevel[self.selectedchannel])
                else: self.setdaclevelforchan(self.selectedchannel,self.lowdaclevelac[self.selectedchannel])
            else: #supergain
                if self.acdc[self.selectedchannel]: self.setdaclevelforchan(self.selectedchannel,self.lowdaclevelsuper[self.selectedchannel]) #dc super gain
                else: self.setdaclevelforchan(self.selectedchannel,self.lowdaclevelsuperac[self.selectedchannel])
        else: # high gain
            if self.supergain[self.selectedchannel]: 
                if self.acdc[self.selectedchannel]: self.setdaclevelforchan(self.selectedchannel,self.highdaclevel[self.selectedchannel])
                else: self.setdaclevelforchan(self.selectedchannel,self.highdaclevelac[self.selectedchannel])
            else: #supergain
                if self.acdc[self.selectedchannel]: self.setdaclevelforchan(self.selectedchannel,self.highdaclevelsuper[self.selectedchannel]) #dc super gain
                else: self.setdaclevelforchan(self.selectedchannel,self.highdaclevelsuperac[self.selectedchannel])
        
    def setacdc(self):
        chan=self.selectedchannel
        theboard = num_board-1-chan/num_chan_per_board
        chanonboard = chan%num_chan_per_board
        print "toggling acdc for chan",chan,"which is chan",chanonboard,"on board",theboard
        self.acdc[int(chan)] = not self.acdc[int(chan)]
        self.b20= int('00',16)  # shdn (set first char to 0 to turn on) / ac coupling (set second char to f for DC, 0 for AC)
        for c in range(0,4):
            realchan = (num_board-1-theboard)*num_chan_per_board+c
            if self.acdc[int(realchan)]: 
                self.b20 = self.toggleBit(self.b20,int(c)) # 1 is dc, 0 is ac
                print "toggling bit",c,"for chan",realchan
        self.sendi2c("20 13 "+ ('%0*x' % (2,self.b20)),  theboard) #port B of IOexp 1, only for the selected board
        self.setdacvalue()
        self.drawtext()
    
    def setdacvalues(self,sc):
        oldchan=self.selectedchannel
        for chan in range(sc,sc+4):
            self.selectedchannel=chan
            self.setdacvalue()
        self.selectedchannel=oldchan
    
    def storecalib(self):
        cwd = os.getcwd()
        print "current directory is",cwd
        for board in range(0,num_board):
            self.storecalibforboard(board)
    def storecalibforboard(self,board):
        sc = board*num_chan_per_board
        print "storing calibrations for board",board,", channels",sc,"-",sc+4
        c = dict(
            boardID=self.uniqueID[board],
            lowdaclevels=self.lowdaclevel[sc : sc+4].tolist(),
            highdaclevels=self.highdaclevel[sc : sc+4].tolist(),
            lowdaclevelssuper=self.lowdaclevelsuper[sc : sc+4].tolist(),
            highdaclevelssuper=self.highdaclevelsuper[sc : sc+4].tolist(),
            lowdaclevelsac=self.lowdaclevelac[sc : sc+4].tolist(),
            highdaclevelsac=self.highdaclevelac[sc : sc+4].tolist(),
            lowdaclevelssuperac=self.lowdaclevelsuperac[sc : sc+4].tolist(),
            highdaclevelssuperac=self.highdaclevelsuperac[sc : sc+4].tolist()
            )
        #print json.dumps(c,indent=4)
        fname = "calib/calib_"+self.uniqueID[board]+".json.txt"
        json.dump(c,open(fname,'w'),indent=4)
        print "wrote",fname
    
    def readcalib(self):
        cwd = os.getcwd()
        print "current directory is",cwd
        for board in range(0,num_board):
            self.readcalibforboard(board)
    def readcalibforboard(self,board):
        sc = board*num_chan_per_board
        if len(self.uniqueID)<=board:
            print "failed to get board ID for board",board
            self.setdacvalues(sc) #will load in defaults
            return
        print "reading calibrations for board",board,", channels",sc,"-",sc+4
        fname = "calib/calib_"+self.uniqueID[board]+".json.txt"
        try:
            c = json.load(open(fname))
            print "read",fname
            assert c['boardID']==self.uniqueID[board]
            self.lowdaclevel[sc : sc+4] = c['lowdaclevels']
            self.highdaclevel[sc : sc+4] = c['highdaclevels']
            self.lowdaclevelsuper[sc : sc+4] = c['lowdaclevelssuper']
            self.highdaclevelsuper[sc : sc+4] = c['highdaclevelssuper']
            self.lowdaclevelac[sc : sc+4] = c['lowdaclevelsac']
            self.highdaclevelac[sc : sc+4] = c['highdaclevelsac']
            self.lowdaclevelsuperac[sc : sc+4] = c['lowdaclevelssuperac']
            self.highdaclevelsuperac[sc : sc+4] = c['highdaclevelssuperac']            
            self.setdacvalues(sc) #and use the new levels right away
            if not self.firstdrawtext: self.drawtext()
        except IOError:
            print "No calib file found for board",board,"at file",fname
            self.setdacvalues(sc) #will load in defaults      
    
    def onscroll(self,event):
         #print event
         if event.button=='up': self.adjustvertical(True)
         else: self.adjustvertical(False)
        
    def onrelease(self,event): # a key was released
        if event.key=="shift": self.keyShift=False;return
        elif event.key=="alt": self.keyAlt=False;return
        elif event.key=="control": self.keyControl=False; return    
    
    #will grab the next keys as input
    keyResample=False
    keysettriggertime=False
    keydownsample=False
    keySPI=False
    keyi2c=False
    keyLevel=False
    keyShift=False
    keyAlt=False
    keyControl=False    
    
    def onpress(self,event): # a key was pressed
            if self.keyResample:
                try:
                    self.sincresample=int(event.key)
                    print "resample now",self.sincresample
                    if self.sincresample>0: self.xydata=np.empty([num_chan_per_board*num_board,2,self.sincresample*(self.num_samples-1)],dtype=float)
                    else: self.xydata=np.empty([num_chan_per_board*num_board,2,1*(self.num_samples-1)],dtype=float)
                    self.keyResample=False; return
                except ValueError: pass
            elif self.keysettriggertime:
                if event.key=="enter":                    
                    self.settriggertime(self.triggertimethresh)
                    self.keysettriggertime=False; return
                else:
                    self.triggertimethresh=10*self.triggertimethresh+int(event.key)
                    print "triggertimethresh",self.triggertimethresh; return
            elif self.keydownsample:
                if event.key=="enter":
                    self.telldownsample(self.tempdownsample)
                    self.keydownsample=False; return
                else:
                    self.tempdownsample=10*self.tempdownsample+int(event.key)
                    print "tempdownsample",self.tempdownsample; return
            elif self.keySPI:
                if event.key=="enter":                    
                    self.tellSPIsetup(self.SPIval)
                    self.keySPI=False; return
                else:
                    self.SPIval=10*self.SPIval+int(event.key)
                    print "SPIval",self.SPIval; return            
            elif self.keyi2c:
                if event.key=="enter":                    
                    self.sendi2c(self.i2ctemp)
                    self.keyi2c=False; return
                else:
                    self.i2ctemp=self.i2ctemp+event.key
                    print "i2ctemp",self.i2ctemp; return
            elif self.keyLevel:
                if event.key=="enter":
                    self.keyLevel=False
                    s=self.leveltemp.split(",")
                    #print "Got",int(s[0]),int(s[1])
                    self.selectedchannel=int(s[0])
                    self.chanlevel[self.selectedchannel] = int(s[1])
                    self.rememberdacvalue()
                    self.setdacvalue()
                    return
                else:
                    self.leveltemp=self.leveltemp+event.key
                    print "leveltemp",self.leveltemp; return
            elif event.key=="r": self.rolltrigger=not self.rolltrigger; self.tellrolltrig(self.rolltrigger);return
            elif event.key=="p": self.paused = not self.paused;print "paused",self.paused; return
            elif event.key=="P": self.getone = not self.getone;print "get one",self.getone; return
            elif event.key=="a": self.average = not self.average;print "average",self.average; return
            elif event.key=="h": self.togglehighres(); return
            elif event.key=="e": self.toggleuseexttrig(); return
            elif event.key=="A": self.toggleautorearm(); return
            elif event.key=="U": self.toggledousb(); return
            elif event.key=="O": self.oversamp(self.selectedchannel); return
            elif event.key==">": self.refsinchan=self.selectedchannel; self.reffreq=0;
            elif event.key=="t": self.rising=not self.rising;self.settriggertype(self.rising);print "rising toggled",self.rising; return
            elif event.key=="g": self.dogrid=not self.dogrid;print "dogrid toggled",self.dogrid; return
            elif event.key=="x": self.tellswitchgain(self.selectedchannel)
            elif event.key=="ctrl+x": 
                for chan in range(num_chan_per_board*num_board): self.tellswitchgain(chan)
            elif event.key=="X": self.togglesupergainchan(self.selectedchannel)
            elif event.key=="F": self.fftchan=self.selectedchannel; self.dofft=True;return
            elif event.key=="/": self.setacdc();return
            elif event.key=="I": self.testi2c(); return
            elif event.key=="c": self.readcalib(); return
            elif event.key=="C": self.storecalib(); return
            elif event.key=="|": print "starting autocalibration";self.autocalibchannel=0;
            elif event.key=="W": self.domaindrawing=not self.domaindrawing; return
            elif event.key=="Y": self.doxyplot=True; self.xychan=self.selectedchannel; print "doxyplot now",self.doxyplot,"for channel",self.xychan; return;
            elif event.key=="Z": self.recorddata=True; self.recorddatachan=self.selectedchannel; self.recordedchannel=[]; print "recorddata now",self.recorddata,"for channel",self.recorddatachan; return;
            elif event.key=="right": self.telldownsample(self.downsample+1); return
            elif event.key=="left": self.telldownsample(self.downsample-1); return
            elif event.key=="up": self.adjustvertical(True); return
            elif event.key=="down": self.adjustvertical(False); return
            elif event.key=="shift+up": self.adjustvertical(True); return
            elif event.key=="shift+down": self.adjustvertical(False); return
            elif event.key=="ctrl+up": self.adjustvertical(True); return
            elif event.key=="ctrl+down": self.adjustvertical(False); return
            elif event.key=="d": self.tellminidisplaychan(self.selectedchannel);return
            elif event.key=="R": self.keyResample=True;print "now enter amount to sinc resample (0-9)";return
            elif event.key=="T": self.keysettriggertime=True;self.triggertimethresh=0;print "now enter time over/under thresh, then enter";return
            elif event.key=="D": self.keydownsample=True;self.tempdownsample=0;print "now enter downsample amount, then enter";return
            elif event.key=="S": self.keySPI=True;self.SPIval=0;print "now enter SPI code, then enter";return
            elif event.key=="i": self.keyi2c=True;self.i2ctemp="";print "now enter byte in hex for i2c, then enter:";return
            elif event.key=="L": self.keyLevel=True;self.leveltemp="";print "now enter [channel to set level for, level] then enter:";return
            elif event.key=="shift": self.keyShift=True;return
            elif event.key=="alt": self.keyAlt=True;return
            elif event.key=="control": self.keyControl=True;return
            elif event.key=="tab":
                for l in self.lines:
                    self.togglechannel(l)
                self.figure.canvas.draw()
                return;
            try:
                print 'key=%s' % (event.key)
                print 'x=%d, y=%d, xdata=%f, ydata=%f' % (event.x, event.y, event.xdata, event.ydata)
            except TypeError: pass
    
    def on_launch(self):        
        self.xydata=np.empty([num_chan_per_board*num_board,2,self.num_samples-1],dtype=float)
        self.xydataslow=np.empty([len(max10adcchans),2,self.nsamp],dtype=float)
        if self.domaindrawing: self.on_launch_draw()
    
    def on_launch_draw(self):
        plt.ion() #turn on interactive mode
        self.nlines = num_chan_per_board*num_board+len(max10adcchans)
        if self.db: print "nlines=",self.nlines
        self.figure, self.ax = plt.subplots(1)
        for l in np.arange(self.nlines):            
            maxchan=l-num_chan_per_board*num_board
            c=(0,0,0)
            if maxchan>=0:
                board = int(num_board-1-max10adcchans[maxchan][0])
                if board%3==0: c=(1-0.2*maxchan,0,0)
                if board%3==1: c=(0,1-0.2*maxchan,0)
                if board%3==2: c=(0,0,1-0.2*maxchan)
                line, = self.ax.plot([],[], '-', label=str(max10adcchans[maxchan]), color=c, linewidth=0.5, alpha=.5)
            else: 
                board=l/4
                chan=l%4
                if board%3==0: c=(1-0.2*chan,0,0)
                if board%3==1: c=(0,1-0.2*chan,0)
                if board%3==2: c=(0,0,1-0.2*chan)
                line, = self.ax.plot([],[], '-', label="chan "+str(l), color=c, linewidth=1.0, alpha=.9)
            self.lines.append(line)
        #Other stuff
        self.setxaxis(); self.setyaxis();
        self.ax.grid()
        self.vline=0
        otherline , = self.ax.plot([self.vline, self.vline], [-2, 2], 'k--', lw=1)#,label='trigger time vert')
        self.otherlines.append(otherline)
        self.hline = 0
        otherline , = self.ax.plot( [-2, 2], [self.hline, self.hline], 'k--', lw=1)#,label='trigger thresh horiz')
        self.otherlines.append(otherline)
        self.hline2 = 0
        otherline , = self.ax.plot( [-2, 2], [self.hline2, self.hline2], 'k--', lw=1, color='blue')#, label='trigger2 thresh horiz')
        self.otherlines.append(otherline)
        if self.db: print "drew lines in launch",len(self.otherlines)
        self.figure.canvas.mpl_connect('button_press_event', self.onclick)
        self.figure.canvas.mpl_connect('key_press_event', self.onpress)
        self.figure.canvas.mpl_connect('key_release_event', self.onrelease)
        self.figure.canvas.mpl_connect('pick_event', self.onpick)
        self.figure.canvas.mpl_connect('scroll_event', self.onscroll)
        self.leg = self.ax.legend(loc='upper left', bbox_to_anchor=(1.02, 1),
              ncol=1, borderaxespad=0, fancybox=False, shadow=False, fontsize=10)
        self.leg.get_frame().set_alpha(0.4)
        self.figure.subplots_adjust(right=0.80)
        self.figure.subplots_adjust(left=.10)
        self.figure.subplots_adjust(top=.95)
        self.figure.subplots_adjust(bottom=.10)
        self.figure.canvas.set_window_title('Haasoscope')        
        self.lined = dict()
        channum=0
        for legline, origline in zip(self.leg.get_lines(), self.lines):
            legline.set_picker(5)  # 5 pts tolerance
            legline.set_linewidth(2.0)
            origline.set_picker(5)
            #save a reference to the plot line and legend line and channel number, accessible from either line or the channel number
            self.lined[legline] = (origline,legline,channum)
            self.lined[origline] = (origline,legline,channum)
            self.lined[channum] = (origline,legline,channum)
            channum+=1        
        self.drawtext()
        self.figure.canvas.draw()
        #plt.show(block=False)
    
    def on_running(self, theydata, board): #update data for main plot for a board
        if board<0: #hack to tell it the max10adc channel
            chantodraw=-board-1 #draw chan 0 first (when board=-1)
            posi=chantodraw+num_board*num_chan_per_board
            if self.db: print "drawing line",posi
            if self.db: print "ydata[0]=",theydata[0]
            xdatanew=(self.xsampdata-self.num_samples/2.)*(1000.0*pow(2,self.downsample)/self.clkrate/self.xscaling)
            ydatanew=theydata*(3.3/256)#full scale is 3.3V
            if len(self.lines)>posi: # we may not be drawing, so check!
                self.lines[posi].set_xdata(xdatanew)
                self.lines[posi].set_ydata(ydatanew)
            self.xydataslow[chantodraw][0]=xdatanew
            self.xydataslow[chantodraw][1]=ydatanew
        else: #this draws the 4 fast ADC data channels for each board
            for l in np.arange(num_chan_per_board):
                thechan=l+(num_board-board-1)*num_chan_per_board
                if self.db: print "drawing adc line",thechan
                if len(theydata)<=l: print "don't have channel",l,"on board",board; return
                xdatanew = (self.xdata-self.num_samples/2.)*(1000.0*pow(2,self.downsample)/self.clkrate/self.xscaling)
                ydatanew=(127-theydata[l])*(self.yscale/256.) # got to flip it, since it's a negative feedback op amp
                if self.sincresample>0:
                    (ydatanew,xdatanew) = resample(ydatanew, self.num_samples*self.sincresample, t = xdatanew)
                    xdatanew = xdatanew[1*self.sincresample:self.num_samples*self.sincresample]
                    ydatanew = ydatanew[1*self.sincresample:self.num_samples*self.sincresample]
                else:
                    xdatanew = xdatanew[1:self.num_samples]
                    ydatanew = ydatanew[1:self.num_samples]
                if len(self.lines)>thechan: # we may not be drawing, so check!
                    self.lines[thechan].set_xdata(xdatanew)
                    self.lines[thechan].set_ydata(ydatanew)
                self.xydata[l][0]=xdatanew
                self.xydata[l][1]=ydatanew
                if self.doxyplot and (thechan==self.xychan or thechan==(self.xychan+1)): self.drawxyplot(xdatanew,ydatanew,thechan)# the xy plot
                if self.recorddata and thechan==self.recorddatachan: self.dopersistplot(xdatanew,ydatanew)# the persist shaded plot
                if thechan==self.refsinchan and self.reffreq==0: self.fittosin(xdatanew, ydatanew)                    
                if self.autocalibchannel>=0 and thechan==self.autocalibchannel: self.autocalibrate(thechan,ydatanew)
    
    def fittosin(self,xdatanew, ydatanew):
        res = self.fit_sin(xdatanew, ydatanew)
        print res['maxcov'], res['amp'], res['freq'], res['phase'], res['offset']
        print res['freq']*1000000./self.xscaling,'kHz'
        if res['maxcov']<1e-6: self.reffreq = res['freq']
        else: print "sin fit failed!"
        
    #For finding the frequency of a reference sin wave signal, for lockin calculations
    def fit_sin(self,tt, yy):
        '''Fit sin to the input time sequence, and return fitting parameters "amp", "omega", "phase", "offset", "freq", "period" and "fitfunc"'''
        tt = np.array(tt)
        yy = np.array(yy)
        ff = np.fft.fftfreq(len(tt), (tt[1]-tt[0]))   # assume uniform spacing
        Fyy = abs(np.fft.fft(yy))
        guess_freq = abs(ff[np.argmax(Fyy[1:])+1])   # excluding the zero frequency "peak", which is related to offset
        guess_amp = np.std(yy) * 2.**0.5
        guess_offset = np.mean(yy)
        guess = np.array([guess_amp, 2.*np.pi*guess_freq, 0., guess_offset])
    
        def sinfunc(t, A, w, p, c):  return A * np.sin(w*t + p) + c
        popt, pcov = scipy.optimize.curve_fit(sinfunc, tt, yy, p0=guess)
        A, w, p, c = popt
        f = w/(2.*np.pi)
        fitfunc = lambda t: A * np.sin(w*t + p) + c
        return {"amp": A, "omega": w, "phase": p, "offset": c, "freq": f, "period": 1./f, "fitfunc": fitfunc, "maxcov": np.max(pcov), "rawres": (guess,popt,pcov)}
    
    def autocalibrate(self,thechan,ydatanew):
        self.selectedchannel=thechan
        avg = np.average(ydatanew)
        #print avg
        gotonext=False
        tol = 1.0
        tol2 = 0.25
        if self.supergain[self.selectedchannel] or self.gain[self.selectedchannel]: # normal gain or low gain
            tol = 0.3
            tol2 = 0.02
        if avg>0+tol:                        
            self.adjustvertical(False,10)
        elif avg<0-tol:
            self.adjustvertical(True,10)
        elif avg>0+tol2:
            self.adjustvertical(False,1)
        elif avg<0-tol2:
            self.adjustvertical(True,1)
        else: gotonext=True
        if self.chanlevel[self.selectedchannel]==0: gotonext=True
        if gotonext:
            #go to the next channel, unless we're at the end of all channels
            self.autocalibchannel=self.autocalibchannel+1
            if self.autocalibchannel==num_chan_per_board*num_board:
                self.autocalibgainac=self.autocalibgainac+1
                if self.autocalibgainac==1:
                    self.autocalibchannel=0
                    for chan in range(num_chan_per_board*num_board):
                        self.selectedchannel=chan
                        self.setacdc()
                elif self.autocalibgainac==2:
                    self.autocalibchannel=0
                    for chan in range(num_chan_per_board*num_board):
                        self.selectedchannel=chan
                        self.tellswitchgain(chan)
                elif self.autocalibgainac==3:
                    self.autocalibchannel=0
                    for chan in range(num_chan_per_board*num_board):
                        self.selectedchannel=chan
                        self.setacdc()
                else:
                    self.autocalibchannel=-1 #all done
                    self.autocalibgainac=0
                    for chan in range(num_chan_per_board*num_board):
                        self.selectedchannel=chan
                        self.tellswitchgain(chan)
                        self.togglesupergainchan(chan)
                    print "done with autocalibration \a" # beep!
    
    doxyplot=False
    drawnxy=False
    xychan=0
    def drawxyplot(self,xdatanew,ydatanew,thechan):
        if thechan==self.xychan: self.xydataforxaxis=ydatanew #the first channel will define the info on the x-axis
        if thechan==(self.xychan+1):
            if not self.drawnxy: # got to make the plot window the first time
                self.figxy, self.axxy = plt.subplots(1,1)
                self.figxy.canvas.mpl_connect('close_event', self.handle_xy_close)
                self.drawnxy=True
                self.figxy.set_size_inches(6, 6, forward=True)
                self.xyplot, = self.axxy.plot(self.xydataforxaxis,ydatanew) #scatter
                self.figxy.canvas.set_window_title('XY display of channels '+str(self.xychan)+' and '+str(self.xychan+1))
                self.axxy.set_xlabel('Channel '+str(self.xychan)+' Volts')
                self.axxy.set_ylabel('Channel '+str(self.xychan+1)+' Volts')
                self.axxy.set_xlim(self.min_y, self.max_y)
                self.axxy.set_ylim(self.min_y, self.max_y)
                self.axxy.grid()
            #redraw the plot
            self.figxy.canvas.set_window_title('XY display of channels '+str(self.xychan)+' and '+str(self.xychan+1))
            self.axxy.set_xlabel('Channel '+str(self.xychan)+' Volts')
            self.axxy.set_ylabel('Channel '+str(self.xychan+1)+' Volts')
            self.xyplot.set_data(self.xydataforxaxis, ydatanew)
            self.figxy.canvas.draw()
    
    recorddata=False
    recordindex=0 # for recording data, the last N events, for the shaded persist display window
    recordedchannellength=250 #number of events to overlay in the 2d persist plot
    recordedchannel=[]
    drawn2d=False
    def dopersistplot(self,xdatanew,ydatanew):
        if len(self.recordedchannel)<self.recordedchannellength: self.recordedchannel.append(ydatanew)
        else: self.recordedchannel[self.recordindex]=ydatanew
        self.recordindex+=1
        if self.recordindex>=self.recordedchannellength: self.recordindex=0;
        if len(self.recordedchannel)==self.recordedchannellength:
            if not self.drawn2d: # got to make the plot window the first time
                self.fig2d, self.ax2d = plt.subplots(1,1)
                self.fig2d.canvas.mpl_connect('close_event', self.handle_persist_close)
                self.drawn2d=True
            if self.recordindex==0:
                self.ax2d.clear()
                self.ax2d.hist2d(
                    np.tile(xdatanew,self.recordedchannellength), np.concatenate(tuple(self.recordedchannel)), 
                    bins=[min(self.num_samples,1024),256], range=[[xdatanew[0],xdatanew[self.num_samples-1]],[self.min_y,self.max_y]],
                    cmin=1, cmap='rainbow') #, Blues, Reds, coolwarm, seismic
                self.fig2d.canvas.set_window_title('Persist display of channel '+str(self.recorddatachan))
                if self.xscaling==1.e3: self.ax2d.set_xlabel('Time (us)')
                else: self.ax2d.set_xlabel('Time (ms)')
                self.ax2d.set_ylabel('Volts')
                self.ax2d.grid()
                self.fig2d.canvas.draw()
    
    def redraw(self):
        if self.domaindrawing: # don't draw if we're going for speed!
            if dofast:
                self.ax.draw_artist(self.ax.patch)
                if self.dogrid:
                    [self.ax.draw_artist(gl) for gl in self.ax.xaxis.get_gridlines()]
                    [self.ax.draw_artist(gl) for gl in self.ax.yaxis.get_gridlines()]
                if self.needtoredrawtext: [self.ax.draw_artist(l) for l in self.texts]
                self.needtoredrawtext=False
                [self.ax.draw_artist(l) for l in self.lines]
                [self.ax.draw_artist(l) for l in self.otherlines]
                self.figure.canvas.update() #needs Qt4Agg backend
            else:
                self.ax.relim()
                self.ax.autoscale_view()
                self.figure.canvas.draw()
        if len(plt.get_fignums())>0:
            self.figure.canvas.flush_events()
    
    def handle_xy_close(self,evt):
        self.drawnxy=False
        self.doxyplot=False
    def handle_persist_close(self,evt):
        self.drawn2d=False
        self.recorddata=False
    def handle_fft_close(self,evt):
        self.dofft=False
        self.fftdrawn=False
    def handle_lockin_close(self,evt):
        self.dolockinplot=False
        self.lockindrawn=False
    
    fftdrawn=False
    def plot_fft(self,bn): # pass in the board number
        channumonboard = self.fftchan%num_chan_per_board # this is what channel (0--3) we want to draw fft from for the board
        chanonboardnum = num_board - self.fftchan/num_chan_per_board - 1 # this is what board (0 -- (num_board-1)) we want to draw that fft channel from
        if bn==chanonboardnum and len(self.ydata)>channumonboard: # select the right board check that the channel data is really there
            twoforoversampling=1
            if self.dooversample[self.fftchan]: twoforoversampling=2
            y = self.ydata[channumonboard] # channel signal to take fft of
            n = len(y) # length of the signal
            k = np.arange(n)
            uspersample=(1.0/self.clkrate)*pow(2,self.downsample)/twoforoversampling # us per sample = 10 ns * 2^downsample
            t = np.arange(0,1,1.0/n) * (n*uspersample) # time vector in us
            frq = (k/uspersample)[range(n/2)]/n # one side frequency range up to Nyquist
            Y = np.fft.fft(y)[range(n/2)]/n # fft computing and normalization
            Y[0]=0 # to suppress DC
            if not self.fftdrawn: # just the first time, do some setup
                self.fftdrawn=True
                self.fftfig, self.fftax = plt.subplots(2,1)
                self.fftfig.canvas.set_window_title('FFT of channel '+str(self.fftchan))
                self.fftfig.canvas.mpl_connect('close_event', self.handle_fft_close)
                self.fftdataplot, = self.fftax[0].plot(t,y) # plotting the data
                self.fftax[0].set_xlabel('Time (us)')
                self.fftax[0].set_ylabel('Amplitude')
                self.fftfreqplot, = self.fftax[1].plot(frq,abs(Y)) # plotting the spectrum
                self.fftax[1].set_xlabel('Freq (MHz)')
                self.fftax[1].set_ylabel('|Y(freq)|')
                self.fftax[0].set_xlim(0,n*uspersample)
                self.fftax[1].set_xlim(0,frq[n/2-1])
                self.oldmaxt = n*uspersample
                self.oldmaxfreq = frq[n/2-1]
            else: # redrawing
                self.fftdataplot.set_xdata(t)
                self.fftfreqplot.set_xdata(frq)
                self.fftdataplot.set_ydata(y)
                self.fftfreqplot.set_ydata(abs(Y))
                if n*uspersample != self.oldmaxt:
                    self.fftax[0].set_xlim(0,n*uspersample)
                if frq[n/2-1] != self.oldmaxfreq:
                    self.fftax[1].set_xlim(0,frq[n/2-1])
                self.oldmaxfreq = frq[n/2-1]
                self.oldmaxt = n*uspersample
                self.fftax[0].relim()
                self.fftax[1].relim()
                self.fftax[0].autoscale_view()
                self.fftax[1].autoscale_view()
                self.fftfig.canvas.draw()
                self.fftfig.canvas.set_window_title('FFT of channel '+str(self.fftchan))
                self.fftfig.canvas.flush_events()
    
    lockindrawn=False
    def plot_lockin(self):
        trange=100
        t=np.arange(trange)
        if not self.lockindrawn: # just the first time, do some setup
            self.lockiny1=np.zeros(trange)
            self.lockiny2=np.zeros(trange)
            if self.debuglockin: self.lockiny1o=np.zeros(trange) # offline float calculation
            if self.debuglockin: self.lockiny2o=np.zeros(trange) # offline float calculation
            self.lockindrawn=True
            self.lockinfig, self.lockinax = plt.subplots(2,1)
            self.lockinfig.canvas.set_window_title('Lockin of channel '+str(2)+" wrt "+str(3))
            self.lockinfig.canvas.mpl_connect('close_event', self.handle_lockin_close)
            self.lockinamplplot, = self.lockinax[0].plot(t,self.lockiny1) # plotting the amplitude
            self.lockinax[0].set_xlabel(' ')
            self.lockinax[0].set_ylabel('Amplitude')
            self.lockinphaseplot, = self.lockinax[1].plot(t,self.lockiny2) # plotting the phase
            self.lockinax[1].set_xlabel(' ')
            self.lockinax[1].set_ylabel('Phase')
            if self.debuglockin:
                self.lockinamplploto, = self.lockinax[0].plot(t,self.lockiny1o)# offline float calculation
                self.lockinphaseploto, = self.lockinax[1].plot(t,self.lockiny2o)# offline float calculation
        else: # redrawing
            self.lockiny1=np.roll(self.lockiny1,-1)
            self.lockiny2=np.roll(self.lockiny2,-1)
            if hasattr(self,'lockinamp'):
                self.lockiny1[trange-1]=self.lockinamp
                self.lockiny2[trange-1]=self.lockinphase
            if self.debuglockin:
                self.lockiny1o=np.roll(self.lockiny1o,-1)
                self.lockiny2o=np.roll(self.lockiny2o,-1)
                self.lockiny1o[trange-1]=self.lockinampo
                self.lockiny2o[trange-1]=self.lockinphaseo
                self.lockinamplploto.set_ydata(self.lockiny1o)
                self.lockinphaseploto.set_ydata(self.lockiny2o)
            self.lockinamplplot.set_xdata(t)
            self.lockinphaseplot.set_xdata(t)
            self.lockinamplplot.set_ydata(self.lockiny1)
            self.lockinphaseplot.set_ydata(self.lockiny2)
            self.lockinax[0].relim()
            self.lockinax[1].relim()
            self.lockinax[0].autoscale_view()
            self.lockinax[1].autoscale_view()
            self.lockinfig.canvas.draw()
            self.lockinfig.canvas.set_window_title('Lockin of channel '+str(2)+" wrt "+str(3))
            self.lockinfig.canvas.flush_events()

    def getotherdata(self,board):
        debug3=True
        self.ser.write(chr(132)) #delay counter
        num_other_bytes = 1
        rslt = self.ser.read(num_other_bytes)
        if len(rslt)==num_other_bytes:
            byte_array = unpack('%dB'%len(rslt),rslt) #Convert serial data to array of numbers
            if debug3: print "\n delay counter data",byte_array[0],"from board",board
            #if debug3: print "other data",bin(byte_array[0])
        else: print "getotherdata asked for",num_other_bytes,"delay counter bytes and got",len(rslt)
        self.ser.write(chr(133)) #carry counter
        num_other_bytes = 1
        rslt = self.ser.read(num_other_bytes)
        if len(rslt)==num_other_bytes:
            byte_array = unpack('%dB'%len(rslt),rslt) #Convert serial data to array of numbers
            if debug3: print " carry counter data",byte_array[0],"from board",board
            #if debug3: print "other data",bin(byte_array[0])
        else: print "getotherdata asked for",num_other_bytes,"carry counter bytes and got",len(rslt)
    
    def to_int(self,n): # takes a 32 bit decimal number in two's complement and converts to a binary and then to a signed integer
        bin = '{0:32b}'.format(n)
        x = int(bin, 2)
        if bin[0] == '1': # "sign bit", big-endian
            x -= 2**len(bin)
        return x
    
    def lockinanalyzedata(self,board):
        if self.lockinanalyzedataboard!=board: return False
        y2 = self.ydata[2] # channel 2 signal
        y3 = self.ydata[3] # channel 3 signal        
        meany2=np.sum(y2)/self.num_samples
        meany3=np.sum(y3)/self.num_samples
        y2 = y2-meany2
        y3 = y3-meany3
        y3shifted = np.roll(y3,self.numtoshift)        
        res1=y2*y3
        res2=y2*y3shifted
        r1m=np.sum(res1)
        r2m=np.sum(res2)
        #print r1m,r2m
        r1m/=4096.
        r2m/=4096.
        ampl = np.sqrt(r1m*r1m+r2m*r2m)
        phase = 180.*np.arctan2(r2m,r1m)/np.pi
        if self.debuglockin:
            print "no window:  ",r1m.round(2), r2m.round(2), self.numtoshift, meany2.round(1),meany3.round(1)
            print ampl.round(2), phase.round(2), "<------ offline no window"        
        lowerwindowedge = self.numtoshift+1
        upperwindowedge = self.num_samples-self.numtoshift        
        if self.debuglockin:
            self.ydata[0]= y3shifted+127 # to see on screen, alter self.ydata here
            self.ydata[0][0:lowerwindowedge] = np.zeros((lowerwindowedge,), dtype=np.int)+127
            self.ydata[0][upperwindowedge:self.num_samples] = np.zeros((self.num_samples-upperwindowedge,), dtype=np.int)+127        
        y2window = y2[lowerwindowedge:upperwindowedge]
        y3window = y3[lowerwindowedge:upperwindowedge]
        y3shiftedwindow = y3shifted[lowerwindowedge:upperwindowedge]
        res1window=y2window*y3window
        res2window=y2window*y3shiftedwindow
        r1mwindow=np.sum(res1window)
        r2mwindow=np.sum(res2window)
        if self.debuglockin: print "window:",r1mwindow,r2mwindow
        r1mwindow/=4096.
        r2mwindow/=4096.
        amplwindow = np.sqrt(r1mwindow*r1mwindow+r2mwindow*r2mwindow)
        phasewindow = 180.*np.arctan2(r2mwindow,r1mwindow)/np.pi
        if self.debuglockin:
            print "with window:",r1mwindow.round(2), r2mwindow.round(2), self.numtoshift, meany2.round(1),meany3.round(1)
            print amplwindow.round(2), phasewindow.round(2), "<------ offline with window"        
        meany2float=np.mean(self.ydata[2])
        meany3float=np.mean(self.ydata[3])
        y3shiftedfloat = np.roll(self.ydata[3]-meany3float,self.numtoshift)        
        y2windowfloat = self.ydata[2][lowerwindowedge:upperwindowedge]-meany2float
        y3windowfloat = self.ydata[3][lowerwindowedge:upperwindowedge]-meany3float
        y3shiftedwindowfloat = y3shiftedfloat[lowerwindowedge:upperwindowedge]
        res1windowfloat=y2windowfloat*y3windowfloat
        res2windowfloat=y2windowfloat*y3shiftedwindowfloat
        r1mwindowfloat=np.sum(res1windowfloat)
        r2mwindowfloat=np.sum(res2windowfloat)
        #print "windowfloat:",r1mwindowfloat,r2mwindowfloat
        r1mwindowfloat/=4096.
        r2mwindowfloat/=4096.
        amplwindowfloat = np.sqrt(r1mwindowfloat*r1mwindowfloat+r2mwindowfloat*r2mwindowfloat)
        phasewindowfloat = 180.*np.arctan2(r2mwindowfloat,r1mwindowfloat)/np.pi
        if self.debuglockin:
            print "float with window:",r1mwindowfloat.round(2), r2mwindowfloat.round(2), self.numtoshift, meany2.round(1),meany3.round(1)
            print amplwindowfloat.round(2), phasewindowfloat.round(2), "<------ offline with window float\n"
        self.lockinampo = amplwindowfloat
        self.lockinphaseo = phasewindowfloat
    
    def getlockindata(self,board):
            rslt = self.ser.read(16)
            byte_array = unpack('%dB'%len(rslt),rslt) #Convert serial data to array of numbers
            if len(rslt)==16:
                r1_fpga = (256*256*256*byte_array[3]+256*256*byte_array[2]+256*byte_array[1]+byte_array[0])
                r2_fpga =  (256*256*256*byte_array[7]+256*256*byte_array[6]+256*byte_array[5]+byte_array[4])
                r1_fpga = self.to_int(r1_fpga)
                r2_fpga = self.to_int(r2_fpga)
                mean_c2 = (256*256*256*byte_array[11]+256*256*byte_array[10]+256*byte_array[9]+byte_array[8])
                mean_c3 = (256*256*256*byte_array[15]+256*256*byte_array[14]+256*byte_array[13]+byte_array[12])
                if self.debuglockin:
                    print byte_array[0:4], r1_fpga
                    print byte_array[4:8], r2_fpga
                    print byte_array[8:12], mean_c2
                    print byte_array[12:16], mean_c3
                r1_fpga/=4096.
                r2_fpga/=4096.
                ampl_fpga = np.sqrt(r1_fpga*r1_fpga+r2_fpga*r2_fpga)
                phase_fpga = 180.*np.arctan2(r2_fpga,r1_fpga)/np.pi
                if self.lockinanalyzedataboard==board:
                    self.lockinamp = ampl_fpga
                    self.lockinphase = phase_fpga
                if False:
                    print ampl_fpga.round(2), phase_fpga.round(2), "<------ fpga "
            else: print "getdata asked for",16,"lockin bytes and got",len(rslt),"from board",board        
    
    usbsermap=[]
    def makeusbsermap(self): # figure out which board is connected to which USB 2 connection
        self.usbsermap=np.zeros(num_board, dtype=int)
        if len(self.usbser)<num_board:
            print "Not a USB2 connection for each board!"
            return False
        if len(self.usbser)>1:
            for usb in np.arange(num_board): self.usbser[usb].timeout=.5 # lower the timeout on the connections, temporarily
            foundusbs=[]
            for bn in np.arange(num_board):
                self.ser.write(chr(100)) # prime the trigger
                self.ser.write(chr(10+bn))
                for usb in np.arange(len(self.usbser)):
                    if not usb in foundusbs: # it's not already known that this usb connection is assigned to a board
                        rslt = self.usbser[usb].read(self.num_bytes) # try to get data from the board
                        if len(rslt)==self.num_bytes:
                            #print "   got the right nbytes for board",bn,"from usb",usb
                            self.usbsermap[bn]=usb
                            foundusbs.append(usb) # remember that we already have figured out which board this usb connection is for, so we don't bother trying again for another board
                            break # already found which board this usb connection is used for, so bail out
                        #else: print "   got the wrong nbytes for board",bn,"from usb",usb
                    #else: print "   already know what usb",usb,"is for"
            for usb in np.arange(num_board): self.usbser[usb].timeout=self.sertimeout # put back the timeout on the connections
        print "usbsermap is",self.usbsermap
        return True
    
    def getdata(self,board):
        self.ser.write(chr(10+board))
        if self.db: print "asked for data from board",board,time.clock()        
        if self.dolockin: self.getlockindata(board)
        if self.dousb:
            #try:
		rslt = self.usbser[self.usbsermap[board]].read(self.num_bytes)
            	#usbser.flushInput() #just in case
	    #except serial.SerialException: pass
        else:
            rslt = self.ser.read(self.num_bytes)
            #ser.flushInput() #just in case
        if self.db: print "getdata wanted",self.num_bytes,"bytes and got",len(rslt),"from board",board,time.clock()
        byte_array = unpack('%dB'%len(rslt),rslt) #Convert serial data to array of numbers
        if len(rslt)==self.num_bytes:
            db2=False #True #False
            if db2: print byte_array[1:11]
            self.ydata=np.reshape(byte_array,(num_chan_per_board,self.num_samples))            
            if self.dooversample[num_chan_per_board*(num_board-board-1)]: self.oversample(0,2)
            if self.dooversample[num_chan_per_board*(num_board-board-1)+1]: self.oversample(1,3)            
            if self.average:
                for c in np.arange(num_chan_per_board):
                    for i in np.arange(self.num_samples/2):
                        val=(self.ydata[c][2*i]+self.ydata[c][2*i+1])/2
                        self.ydata[c][2*i]=val; self.ydata[c][2*i+1]=val;
        else:
            if not self.db: print "getdata asked for",self.num_bytes,"bytes and got",len(rslt),"from board",board
            print byte_array[0:10]
        
    def oversample(self,c1,c2):
        tempc1=self.ydata[c1][self.num_samples/4:3*self.num_samples/4:1] #just using the half of the data in the middle
        tempc2=self.ydata[c2][self.num_samples/4:3*self.num_samples/4:1]
        adjustmeanandrms=True
        if adjustmeanandrms:
            mean_c1 = np.mean(tempc1)
            rms_c1 = np.sqrt(np.mean((tempc1-mean_c1)**2))
            mean_c2 = np.mean(tempc2)
            rms_c2 = np.sqrt(np.mean((tempc2-mean_c2)**2))
            meanmean=(mean_c1+mean_c2)/2.
            meanrms=(rms_c1+rms_c2)/2.
            tempc1=meanrms*(tempc1-mean_c1)/rms_c1 + meanmean
            tempc2=meanrms*(tempc2-mean_c2)/rms_c2 + meanmean
            #print mean_c1, mean_c2, rms_c1, rms_c2
        mergedsamps=np.empty(self.num_samples)
        mergedsamps[0:self.num_samples:2]=tempc1 # a little tricky which is 0 and which is 1 (i.e. which is sampled first!)
        mergedsamps[1:self.num_samples+1:2]=tempc2
        self.ydata[c1]=mergedsamps
        self.ydata[c2]=0
    
    def getmax10adc(self,bn):
        chansthisboard = [(x,y) for (x,y) in max10adcchans if x==bn]
        #if self.db: print "getting",chansthisboard
        for chans in chansthisboard:
            chan=chans[1]
            #chan: 110=ain1, 111=pin6, ..., 118=pin14, 119=temp
            self.ser.write(chr(chan))
            if self.db: print "getting max10adc chan",chan,"for bn",bn
            rslt = self.ser.read(self.nsamp*2) #read N bytes (2 per sample)
            if self.db: print "getmax10adc got bytes:",len(rslt)
            if len(rslt)!=(self.nsamp*2): 
                print "getmax10adc got bytes:",len(rslt),"for board",bn,"and chan",chan
                return
            byte_array = unpack('%dB'%len(rslt),rslt) #Convert serial data to array of numbers
            db2=False #True #False
            self.ysampdata[self.max10adcchan-1]=np.add(np.multiply(256,byte_array[1:2*self.nsamp:2]),byte_array[0:2*self.nsamp:2])
            self.ysampdata[self.max10adcchan-1]/=16
            if db2:
                for samp in np.arange(10):
                    code=256*byte_array[1+2*samp]+byte_array[2*samp]
                    self.ysampdata[self.max10adcchan-1][samp]=code/16
                    if chan==119:
                        temp=-3.056e-4*code*code+1.763*code-2325.049
                        print samp,chan,code,round(temp,1),"C",round(temp*1.8+32,1),"F"
                    else: print samp,chan,code,round( (3.3*code)/pow(2,12) ,4),"V"
            self.on_running(self.ysampdata[self.max10adcchan-1], -self.max10adcchan)
            self.max10adcchan+=1

    def getchannels(self):
        if not self.autorearm:
            if self.db: print "priming trigger",time.clock()
            if self.db: time.sleep(.1)
            self.ser.write(chr(100))
        self.max10adcchan=1
        for bn in np.arange(num_board):
            if self.db: print "getting board",bn,time.clock()
            self.getdata(bn) #this sets all boards before this board into serial passthrough mode, so this and following calls for data will go to this board and then travel back over serial
            self.getmax10adc(bn) # get data from 1 MHz Max10 ADC channels
            if self.dogetotherdata: self.getotherdata(bn) # get other data, like TDC info, or other bytes
            if self.dofft: self.plot_fft(bn) #do the FFT plot
            if self.dolockin and self.debuglockin: 
                if sendincrement==0: self.lockinanalyzedata(bn)
                else: print "you need to set sendincrement = 0 first before debugging lockin info"; return False
            if self.dolockin and self.dolockinplot: self.plot_lockin()
            self.on_running(self.ydata, bn) #update data in main window
            if self.db: print "done with board",bn,time.clock()
        return True

    #initialization
    def init(self):
            self.ser.write(chr(0))#tell them their IDs... first one gets 0, next gets 1, ...
            self.ser.write(chr(20+(num_board-1)))#tell them which is the last board
            self.tellrolltrig(self.rolltrigger)
            self.tellsamplesmax10adc()
            self.tellsamplessend()
            self.tellbytesskip()
            self.telldownsample(self.downsample); self.telltickstowait()
            self.togglehighres()
            self.settriggertime(self.triggertimethresh)
            self.tellserialdelaytimerwait()
            self.tellSPIsetup(0) #0.9V CM but not connected
            self.tellSPIsetup(11) #offset binary output
            #tellSPIsetup(12) #offset binary output and divide clock by 2
            #self.tellSPIsetup(30) # multiplexed output
            self.tellSPIsetup(32) # non-multiplexed output (less noise)
            self.setupi2c() # sets all ports to be outputs
            self.toggledousb() # switch to USB2 connection for readout of events, if available
            if self.dousb:
                if not self.makeusbsermap(): return False # figure out which usb connection has which board's data
            self.getIDs() # get the unique ID of each board, for calibration etc.
            self.readcalib() # get the calibrated DAC values for each board; if it fails then use defaults
            return True
    
    #cleanup
    def cleanup(self):
        try:
            self.setbacktoserialreadout()
            self.resetchans()
            if self.autorearm: self.toggleautorearm()
            if self.dohighres: self.togglehighres()
            if self.useexttrig: self.toggleuseexttrig()
            if self.serport!="" and hasattr(self,'ser'):
                self.shutdownadcs()
                for p in self.usbser: p.close()
                self.ser.close()
        except SerialException:
            print "failed to talk to board when cleaning up!"
        plt.close()
        print "bye bye!"
    
    #For setting up serial and USB connections
    def setup_connections(self):
        adjustedbrate=1./(1./self.brate+2.*self.serialdelaytimerwait*1.e-6/(32.*11.)) # delay of 2*serialdelaytimerwait microseconds every 32*11 bits
        serialrate=adjustedbrate/11./(self.num_bytes*num_board+len(max10adcchans)*self.nsamp) #including start+2stop bits
        print "rate theoretically",round(serialrate,2),"Hz over serial"
        ports = list(serial.tools.list_ports.comports()); ports.sort(reverse=True)
        autofindusbports = len(self.usbport)==0
        if self.serport=="" or True:
            for port_no, description, address in ports: print port_no,":",description,":",address
        for port_no, description, address in ports:
            if self.serport=="":
                if '1A86:7523' in address or '1a86:7523' in address: self.serport = port_no
            if autofindusbports:
                if "USB Serial" in description or "Haasoscope" in description: self.usbport.append(port_no)
        if self.serport!="":
            try:
                self.ser = Serial(self.serport,self.brate,timeout=self.sertimeout,stopbits=2)
            except SerialException:
                print "Could not open",self.serport,"!"; return False
            print "connected serial to",self.serport,", timeout",self.sertimeout,"seconds"
        else: self.ser=""
        for p in self.usbport:
            self.usbser.append(Serial(p,timeout=self.sertimeout))
            print "connected USBserial to",p,", timeout",self.sertimeout,"seconds"
        if self.serport=="": print "No serial COM port opened!"; return False
        return True