<table width="100%" class="mainWindow">
<tr><td class="mainWindowHead">
<p>Utstyrsgrupper</p>
</td></tr>

<tr><td>
<?php
include("loginordie.php");
loginOrDie();
?>
<p>Her kan du endre og opprette nye utstyrsgrupper. Utstyrsgruppene kan du koble direkte til varslinger inne i profilene.

<p><a href="#nygruppe">Legg til ny utstyrsgruppe</a>

<?php

$brukernavn = session_get('bruker'); $uid = session_get('uid');

if ($subaction == 'endret') {

	if (post_get('gid') > 0) { 

		$dbh->endreUtstyrgruppe(post_get('gid'), post_get('navn'), post_get('descr') );
		unset($navn);
		unset($descr);
		print "<p><font size=\"+3\">OK</font>, utstyrsgruppenavnet er endret.";

	} else {
		print "<p><font size=\"+3\">Feil</font> oppstod, navnet er <b>ikke</b> endret.";
	}

	// Viser feilmelding om det har oppstått en feil.
	if ( $error != NULL ) {
		print $error->getHTML();
		$error = NULL;
	}
  
}

if ($subaction == 'slett') {

	if (get_get('gid') > 0) { 	
		$dbh->slettUtstyrgruppe(get_get('gid') );

		print "<p><font size=\"+3\">OK</font>, utstyrsgruppen er slettet fra databasen.";

	} else {
		print "<p><font size=\"+3\">Feil</font>, utstyrsgruppen er <b>ikke</b> slettet.";
	}

	// Viser feilmelding om det har oppstått en feil.
	if ( $error != NULL ) {
		print $error->getHTML();
		$error = NULL;
	}
  
}



if ($subaction == "nygruppe") {
	print "<h3>Registrerer ny utstyrsgruppe...</h3>";
  
	$error = NULL;
	if ($navn == "") $navn = "Uten navn";
	if ($uid > 0) { 

		$matchid = $dbh->nyUtstyrgruppeAdm(post_get('navn'), post_get('descr') );
		print "<p><font size=\"+3\">OK</font>, en ny utstyrsgruppe er lagt til.";
    
	} else {
		print "<p><font size=\"+3\">Feil</font>, ny match er <b>ikke</b> lagt til i databasen.";
	}

	// Viser feilmelding om det har oppstått en feil.
	if ( $error != NULL ) {
		print $error->getHTML();
		$error = NULL;
	}
}




if (session_get('admin') >= 100) {


$l = new Lister( 113,
		array('Navn', '#perioder', '#filtre', 'Valg..'),
		array(50,  15, 15, 20),
		array('left',  'right', 'right', 'right'),
		array(true, true, true, false),
		0
);


print "<h3>Felles utstyrsgrupper</h3>";

if ( get_exist('sortid') )
	$l->setSort(get_get('sort'), get_get('sortid') );
$utst = $dbh->listUtstyrAdm($l->getSort() );

for ($i = 0; $i < sizeof($utst); $i++) {


  if ($utst[$i][2] > 0 ) 
    { $ap = $utst[$i][2]; }
  else 
    {
      $ap = "<img alt=\"Ingen\" src=\"icons/stop.gif\">";
    }
    
  if ($utst[$i][3] > 0 ) 
    { $af = $utst[$i][3]; }
  else 
    {
      $af = "<img alt=\"Ingen\" src=\"icons/stop.gif\">";
    }    

	if ($utst[$i][4] == 't' ) { 
		$valg = '<a href="index.php?action=utstyrgrp&gid=' . $utst[$i][0]. 
			'">' . '<img alt="Open" src="icons/open2.gif" border=0></a>&nbsp;' .
			'<a href="index.php?action=futstyr&subaction=endre&gid=' . 
			$utst[$i][0] . '#nygruppe">' .
			'<img alt="Edit" src="icons/edit.gif" border=0></a>&nbsp;' .
			'<a href="index.php?action=futstyr&subaction=slett&gid=' . 
			$utst[$i][0] . '">' .
			'<img alt="Delete" src="icons/delete.gif" border=0></a>';;
			
	} else {
		$valg = "&nbsp;";
    }

	$l->addElement( array("<p>" . $utst[$i][1],  // navn
		$ap, $af, // verdi
		$valg ) 
	);

	$inh = new HTMLCell("<p class=\"descr\">" . $utst[$i][5] . "</p>");	  
	$l->addElement (&$inh);
}

print $l->getHTML();

print "<p>[ <a href=\"index.php?action=" . $action. "&fid=" . $fid. "\">Refresh <img src=\"icons/refresh.gif\" alt=\"Refresh\" border=0> ]</a> ";
print "Antall filtre: " . sizeof($utst);


}


if (!isset($descr)) $descr = "Beskrivelse :";
?>

<a name="nygruppe"></a><p>
<?php
if ($subaction == 'endre') {
	print '<h2>Endre navn på utstyrsgruppe</h2>';
} else {
	print '<h2>Legg til ny utstyrsgruppe</h2>';
}
?>

<form name="form1" method="post" action="index.php?action=futstyr&subaction=<?php
if ($subaction == 'endre') echo "endret"; else echo "nygruppe";
?>">

<?php
if ($subaction == 'endre') {
	print '<input type="hidden" name="gid" value="' . get_get('gid') . '">';
	$old_values = $dbh->utstyrgruppeInfo( get_get('gid') );
}
?>
  <table width="100%" border="0" cellspacing="0" cellpadding="3">
    

    
    <tr>
    	<td width="30%"><p>Navn</p></td>
    	<td width="70%"><input name="navn" type="text" size="40" 
value="<?php echo $old_values[0]; ?>"></select>
        </td>
   	</tr>

    <tr>
    	<td colspan="2"><textarea name="descr" cols="60" rows="4">
<?php echo $old_values[1]; ?></textarea>  </td>
   	</tr>

    <tr>
      <td>&nbsp;</td>
      <td align="right"><input type="submit" name="Submit" value="<?php
if ($subaction == 'endre') echo "Lagre endringer"; else echo "Legg til ny utstyrgruppe";
?>"></td>
    </tr>
  </table>

</form>


</td></tr>
</table>
